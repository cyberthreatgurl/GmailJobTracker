"""API endpoint views.

Extracted from monolithic views.py (Phase 5 refactoring).
Provides API endpoints for frontend JavaScript to poll application state.
"""

from datetime import datetime
from django.http import JsonResponse


def ingestion_status_api(request):
    """API endpoint to check if Gmail ingestion is currently running."""
    import psutil

    # Check if any process is running ingest_gmail
    is_running = False
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if cmdline and any("ingest_gmail" in str(arg) for arg in cmdline):
                is_running = True
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return JsonResponse(
        {"is_running": is_running, "timestamp": datetime.now().isoformat()}
    )


def company_search_api(request):
    """JSON API for company name typeahead search.

    GET /api/company_search/?q=<query>&limit=<n>
    Returns: [{"id": 1, "name": "Acme Corp"}, ...]
    """
    from tracker.models import Company

    query = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 20)), 50)

    if len(query) < 1:
        return JsonResponse([], safe=False)

    results = (
        Company.objects.filter(name__icontains=query)
        .order_by("name")
        .values("id", "name")[:limit]
    )
    return JsonResponse(list(results), safe=False)


__all__ = ["ingestion_status_api", "company_search_api"]
