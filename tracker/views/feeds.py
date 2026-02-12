"""RSS/Feed endpoints.

Provides a small RSS stub for common feed paths to reduce 404 noise.
"""

from django.http import HttpResponse
from django.utils import timezone


def rss_stub(_request):
    """Return a minimal RSS response for unsupported feed URLs."""
    now = timezone.now().strftime("%a, %d %b %Y %H:%M:%S %z")
    xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\">"
        "<channel>"
        "<title>GmailJobTracker</title>"
        "<link>/</link>"
        "<description>No RSS feed is configured for this site.</description>"
        f"<lastBuildDate>{now}</lastBuildDate>"
        "</channel>"
        "</rss>"
    )
    return HttpResponse(xml, content_type="application/rss+xml")
