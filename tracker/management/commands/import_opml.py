
import xml.etree.ElementTree as ET
from pathlib import Path
from django.core.management.base import BaseCommand
from tracker.models import RSSFeed

class Command(BaseCommand):
    help = "Import RSS feeds from an OPML file."

    def add_arguments(self, parser):
        parser.add_argument(
            "opml_file",
            type=str,
            nargs="?",
            default="feedbro-subscriptions-20260310-110531.opml",
            help="Path to the OPML file (default: feedbro-subscriptions-20260310-110531.opml)",
        )

    def handle(self, *args, **options):
        opml_path = Path(options["opml_file"])
        if not opml_path.exists():
            self.stdout.write(self.style.ERROR(f"File not found: {opml_path}"))
            return

        self.stdout.write(f"Parsing {opml_path}...")
        
        try:
            tree = ET.parse(opml_path)
            root = tree.getroot()
            body = root.find("body")

            if body is None:
                self.stdout.write(self.style.ERROR("Invalid OPML: No <body> tag found."))
                return

            # OPML structure can be flat or nested
            # We will process both.
            
            count = 0
            updated = 0
            
            def process_outlines(element, category="Uncategorized"):
                nonlocal count, updated
                for outline in element.findall("outline"):
                    text = outline.get("text") or outline.get("title")
                    xml_url = outline.get("xmlUrl")
                    html_url = outline.get("htmlUrl")
                    type_attr = outline.get("type")

                    # If it has an xmlUrl, it's a feed
                    if xml_url:
                        # Create or update
                        feed, created = RSSFeed.objects.update_or_create(
                            feed_url=xml_url,
                            defaults={
                                "title": text,
                                "site_url": html_url,
                                "category": category,
                                "is_active": True
                            }
                        )
                        if created:
                            count += 1
                            self.stdout.write(self.style.SUCCESS(f"Created: {text} ({category})"))
                        else:
                            updated += 1
                            # self.stdout.write(f"Updated: {text}")
                            
                    # If no xmlUrl, it might be a folder (category)
                    else:
                        sub_category = text if text else category
                        # recurse
                        process_outlines(outline, sub_category)

            process_outlines(body)
            self.stdout.write(self.style.SUCCESS(f"Import complete. Created {count} feeds, Updated {updated} feeds."))

        except ET.ParseError as e:
            self.stdout.write(self.style.ERROR(f"XML Parse Error: {e}"))
        except Exception as e:
             self.stdout.write(self.style.ERROR(f"Error: {e}"))
