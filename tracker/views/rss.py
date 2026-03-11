
import json
import logging
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.conf import settings
from tracker.models import RSSFeed, RSSArticle, Company
import feedparser
from tracker.management.commands.import_opml import Command as ImportOpmlCommand
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

@login_required
def rss_dashboard(request):
    """
    Main RSS Feed Dashboard.
    """
    query = request.GET.get("q", "")
    feed_id = request.GET.get("feed")
    category = request.GET.get("category")
    page_number = request.GET.get("page", 1)
    
    # Base QuerySet
    qs = RSSArticle.objects.select_related("feed", "company").all()
    
    # Filters
    if feed_id:
        qs = qs.filter(feed_id=feed_id)
    if category:
        qs = qs.filter(feed__category=category)
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query))
    
    # Pagination
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(page_number)
    
    # Context data
    feeds = RSSFeed.objects.filter(is_active=True).order_by("category", "title")
    categories = RSSFeed.objects.filter(is_active=True).values_list("category", flat=True).distinct().order_by("category")
    
    return render(request, "tracker/rss_dashboard.html", {
        "page_obj": page_obj,
        "feeds": feeds,
        "categories": categories,
        "query": query,
        "selected_feed": int(feed_id) if feed_id else None,
        "selected_category": category,
    })

@login_required
def fetch_feeds_ajax(request):
    """
    Trigger fetching of RSS feeds via AJAX.
    """
    if request.method != "POST":
         return JsonResponse({"success": False, "error": "Invalid method"}, status=405)
         
    try:
        from django.core.management import call_command
        # This runs synchronously; for production, offload to task queue
        call_command("fetch_rss")
        return JsonResponse({"success": True})
    except Exception as e:
        logger.error(f"Error fetching feeds: {e}")
        return JsonResponse({"success": False, "error": str(e)})

@login_required
def link_article_to_company(request, article_id):
    """
    Link a news article to a Company.
    """
    if request.method != "POST":
         return JsonResponse({"success": False, "error": "Invalid method"}, status=405)
         
    article = get_object_or_404(RSSArticle, pk=article_id)
    company_id = request.POST.get("company_id")
    
    try:
        if not company_id or company_id == "0":
            article.company = None
            article.save()
            return JsonResponse({
                "success": True, 
                "company_name": None, 
                "company_id": None
            })
            
        company = get_object_or_404(Company, pk=company_id)
        article.company = company
        article.save()
        
        return JsonResponse({
            "success": True,
            "company_name": company.name,
            "company_id": company.id
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

@login_required
def add_feed(request):
    """
    Add a new RSS Feed and update OPML.
    """
    if request.method == "POST":
        feed_url = request.POST.get("feed_url")
        category = request.POST.get("category", "Uncategorized")
        
        if not feed_url:
            messages.error(request, "Feed URL is required.")
            return redirect("rss_dashboard")
            
        # 1. Validate Feed
        try:
            d = feedparser.parse(feed_url)
            if d.bozo and not d.entries: # Strict check?
                 messages.warning(request, f"Warning: Feed might be invalid ({d.bozo_exception}), but adding anyway.")
            
            title = d.feed.get("title", feed_url)
            link = d.feed.get("link", "")
            
            # 2. Save to DB
            feed, created = RSSFeed.objects.get_or_create(
                feed_url=feed_url,
                defaults={
                    "title": title,
                    "site_url": link,
                    "category": category,
                    "is_active": True
                }
            )
            
            if not created:
                 messages.info(request, "Feed already exists.")
            else:
                 messages.success(request, "Feed added successfully.")
                 
            # 3. Update OPML File
            _update_opml_add(feed)

        except Exception as e:
            messages.error(request, f"Error adding feed: {e}")
            
    return redirect("rss_dashboard")

@login_required
def delete_feed(request, feed_id):
    """
    Delete an RSS Feed and remove from OPML.
    """
    if request.method == "POST":
        feed = get_object_or_404(RSSFeed, pk=feed_id)
        feed_url = feed.feed_url
        feed.delete()
        
        # Update OPML
        _update_opml_remove(feed_url)
        
        messages.success(request, "Feed deleted.")
        
    return redirect("rss_dashboard")


# --- OPML Helpers ---

OPML_FILE = Path("feedbro-subscriptions-20260310-110531.opml")

def _update_opml_add(feed):
    """
    Add a feed to the OPML file.
    """
    if not OPML_FILE.exists():
        return # Should probably init it

    try:
        tree = ET.parse(OPML_FILE)
        root = tree.getroot()
        body = root.find("body")
        
        # Check if category folder exists
        category_outline = None
        for outline in body.findall("outline"):
            if not outline.get("xmlUrl") and outline.get("text") == feed.category:
                category_outline = outline
                break
        
        if not category_outline:
            # Create category folder
            category_outline = ET.SubElement(body, "outline", text=feed.category, title=feed.category)
            
        # Add feed outline
        ET.SubElement(category_outline, "outline", 
                      text=feed.title, 
                      title=feed.title, 
                      type="rss", 
                      xmlUrl=feed.feed_url, 
                      htmlUrl=feed.site_url or "")
        
        # Indent and save
        _indent(root)
        tree.write(OPML_FILE, encoding="UTF-8", xml_declaration=True)
            
    except Exception as e:
        logger.error(f"Failed to update OPML: {e}")

def _update_opml_remove(feed_url):
    """
    Remove a feed from the OPML file.
    """
    if not OPML_FILE.exists():
        return

    try:
        tree = ET.parse(OPML_FILE)
        root = tree.getroot()
        body = root.find("body")
        
        # Recursive search to remove
        def remove_node(parent):
            for child in parent.findall("outline"):
                if child.get("xmlUrl") == feed_url:
                    parent.remove(child)
                    return True
                if remove_node(child):
                    return True
            return False

        remove_node(body)
        tree.write(OPML_FILE, encoding="UTF-8", xml_declaration=True)
        
    except Exception as e:
        logger.error(f"Failed to update OPML: {e}")

def _indent(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for child in elem:
            _indent(child, level+1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i
