"""
tracker_logger.py

Provides a logger that writes all console messages to a daily log file under logs/ with
timestamps. Each day a new file is used (tracker-YYYY-MM-DD.log).

Usage:
    from tracker_logger import log_console
    log_console("Your message")

Optionally, monkey-patch print to also log to file.
"""

import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)


def log_console(message):
    """Write a timestamped message to a daily log file (tracker-YYYY-MM-DD.log)."""
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    # Compute today's file name at call time so midnight rollovers create a new file automatically
    log_path = os.path.join(LOG_DIR, f"tracker-{now.strftime('%Y-%m-%d')}.log")
    entry = f"[{ts}] {message}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)
    print(entry, end="")


# Optional: monkey-patch print to also log
# import builtins
# orig_print = builtins.print
# def patched_print(*args, **kwargs):
#     msg = ' '.join(str(a) for a in args)
#     log_console(msg)
# builtins.print = patched_print
