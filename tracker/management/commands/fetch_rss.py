
import logging
import feedparser
import json
import socket
from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from tracker.models import RSSFeed, RSSArticle

# Setup logging
logger = logging.getLogger("tracker.rss")
if not logger.handlers:
    console = logging.StreamHandler()
    logger.addHandler(console)
    logger.setLevel(logging.INFO)

class Command(BaseCommand):
    help = "Fetch latest articles from subscribed RSS feeds."

    def handle(self, *args, **options):
        feeds = RSSFeed.objects.filter(is_active=True)
        total_feeds = feeds.count()
        self.stdout.write(f"Fetching updates for {total_feeds} feeds...")

        updated_count = 0
        new_articles = 0
        errors = 0

        # Set socket timeout for feedparser
        socket.setdefaulttimeout(10)

        for feed in feeds:
            try:
                self.stdout.write(f"  Fetching: {feed.title} ({feed.feed_url})")
                d = feedparser.parse(feed.feed_url)

                if d.bozo:
                    logger.warning(f"Feed error for {feed.title}: {d.bozo_exception}")
                    # Continue anyway, sometimes bozo is just encoding issues

                # Check status
                status = getattr(d, "status", 200)
                if status >= 400:
                    logger.error(f"HTTP Error {status} fetching {feed.feed_url}")
                    errors += 1
                    continue

                feed_articles_count = 0
                for entry in d.entries:
                    # Logic to extract unique ID
                    guid = entry.get("id", entry.get("link", ""))
                    if not guid:
                        continue

                    # Check if exists
                    if RSSArticle.objects.filter(guid=guid).exists():
                        continue

                    # Parse date
                    pub_date = None
                    if "published_parsed" in entry:
                         try:
                             pub_date = datetime(*entry.published_parsed[:6], tzinfo=None) # naive UTC first
                             pub_date = timezone.make_aware(pub_date, dt_timezone.utc)
                         except Exception:
                             pass
                    elif "updated_parsed" in entry:
                         try:
                             pub_date = datetime(*entry.updated_parsed[:6], tzinfo=None)
                             pub_date = timezone.make_aware(pub_date, dt_timezone.utc)
                         except Exception:
                             pass

                    if not pub_date:
                        pub_date = timezone.now()

                    # Create article
                    RSSArticle.objects.create(
                        feed=feed,
                        title=entry.get("title", "No Title"),
                        link=entry.get("link", ""),
                        description=entry.get("summary", "") or entry.get("description", ""),
                        author=entry.get("author", ""),
                        pub_date=pub_date,
                        guid=guid,
                    )
                    new_articles += 1
                    feed_articles_count += 1

                feed.last_fetched = timezone.now()
                feed.save(update_fields=["last_fetched"])
                updated_count += 1

            except Exception as e:
                logger.error(f"Error fetching {feed.title}: {e}")
                errors += 1

        self.stdout.write(self.style.SUCCESS(f"Complete. Updated {updated_count}/{total_feeds} feeds. New articles: {new_articles}. Errors: {errors}"))
