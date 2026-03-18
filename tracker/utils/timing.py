"""Reusable timing utilities for views and management commands.

Usage in a view:
    from tracker.utils.timing import timed_block

    with timed_block("resolve_company"):
        company = resolver.resolve(subject, sender)

Usage in a management command (also prints to terminal):
    with timed_block("fetch gmail page 1", stdout=self.stdout):
        msgs = fetch_all_messages(service, max_results=100)

Logs to the 'perf' logger at INFO; escalates to WARNING above 1 000 ms.
threshold_ms can be set > 0 to suppress noise for very fast operations.
"""

import logging
import time
from contextlib import contextmanager

_logger = logging.getLogger("perf")


@contextmanager
def timed_block(label: str, stdout=None, threshold_ms: float = 0):
    """Context manager that measures and logs elapsed time for a named block.

    Args:
        label:        Human-readable name shown in the log / terminal line.
        stdout:       If supplied (e.g. management command self.stdout), also
                      writes to stdout so timing appears in the terminal.
        threshold_ms: Only log if elapsed >= this many milliseconds (default 0
                      means always log).
    """
    t0 = time.perf_counter()
    elapsed_ms = 0.0
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1_000
    if elapsed_ms < threshold_ms:
        return
    level = logging.WARNING if elapsed_ms >= 1_000 else logging.INFO
    _logger.log(level, "TIMING [%s] %.0fms", label, elapsed_ms)
    if stdout is not None:
        stdout.write(f"  [{elapsed_ms:.0f}ms] {label}\n")
