"""Request timing middleware for GmailJobTracker.

Captures per-request wall-clock time and DB query metrics using Django's
execute_wrapper — works with or without DEBUG=True.

Logs PERF lines to the 'perf' logger:
  > 300 ms  → INFO
  > 1 000 ms → WARNING

Adds X-Response-Time-Ms header to every response (visible in
browser DevTools → Network tab).
"""

import logging
import threading
import time

from django.db import connection

logger = logging.getLogger("perf")

_local = threading.local()

_WARN_MS = 1_000       # escalate to WARNING
_INFO_MS = 300         # escalate to INFO; below this → DEBUG only
_SLOW_QUERY_MS = 150   # flag individual queries in a second log line


def _db_timing_wrapper(execute, sql, params, many, context):
    """DB execute_wrapper: accumulates per-query timings in thread-local storage."""
    t0 = time.perf_counter()
    try:
        return execute(sql, params, many, context)
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1_000
        bucket = getattr(_local, "queries", None)
        if bucket is not None:
            bucket.append((elapsed_ms, sql))


class RequestTimingMiddleware:
    """Wraps every HTTP request with timing instrumentation.

    Log line breakdown:
        total   — wall-clock from first byte in to last byte out
        db      — sum of all SQL execution times (via execute_wrapper)
        n_q     — number of SQL statements executed
        slowest — single slowest query in this request
        app     — total minus db (templates, Python logic, JSON file I/O, etc.)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.queries = []
        t0 = time.perf_counter()

        with connection.execute_wrapper(_db_timing_wrapper):
            response = self.get_response(request)

        elapsed_ms = (time.perf_counter() - t0) * 1_000
        queries = list(getattr(_local, "queries", []))
        _local.queries = []  # release memory

        query_count = len(queries)
        query_ms = sum(ms for ms, _ in queries)
        app_ms = elapsed_ms - query_ms
        slowest_ms = max((ms for ms, _ in queries), default=0.0)

        response["X-Response-Time-Ms"] = f"{elapsed_ms:.0f}"

        level = (
            logging.WARNING if elapsed_ms > _WARN_MS
            else logging.INFO if elapsed_ms > _INFO_MS
            else logging.DEBUG
        )
        logger.log(
            level,
            "PERF %s %s → %dms total | %d queries %dms db (slowest %dms) | %dms app",
            request.method,
            request.path,
            elapsed_ms,
            query_count,
            query_ms,
            slowest_ms,
            app_ms,
        )

        slow_sqls = [
            f"  [{ms:.0f}ms] {sql[:120]!r}"
            for ms, sql in queries
            if ms >= _SLOW_QUERY_MS
        ]
        if slow_sqls:
            logger.warning(
                "SLOW QUERIES on %s %s:\n%s",
                request.method,
                request.path,
                "\n".join(slow_sqls),
            )

        return response
