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


__all__ = ["ingestion_status_api"]
