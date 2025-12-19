"""Pytest configuration for GmailJobTracker tests."""

# Ensure project root is on sys.path for imports during pytest collection
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# If DJANGO_SETTINGS_MODULE isn't set by environment, default to dashboard.settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
