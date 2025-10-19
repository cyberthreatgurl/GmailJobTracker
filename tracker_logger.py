"""
tracker_logger.py

Provides a logger that writes all console messages to logs/tracker.log with timestamp.
Usage:
    from tracker_logger import log_console
    log_console("Your message")

Optionally, monkey-patch print to also log to file.
"""

import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_PATH = os.path.join(LOG_DIR, "tracker.log")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)


def log_console(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {message}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    print(entry, end="")


# Optional: monkey-patch print to also log
# import builtins
# orig_print = builtins.print
# def patched_print(*args, **kwargs):
#     msg = ' '.join(str(a) for a in args)
#     log_console(msg)
# builtins.print = patched_print
