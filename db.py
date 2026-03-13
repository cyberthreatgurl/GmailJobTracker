"""Database operations and utilities for job tracker."""
import os
from pathlib import Path
PATTERNS_PATH = Path(__file__).parent / "json/patterns.json"
COMPANIES_PATH = Path(__file__).parent / "json/companies.json"
def is_valid_company(name):
    if not name:
        return False
    name = name.strip()
    if not name or len(name.split()) > 8:
        return False
    if not any(c.isalpha() for c in name):
        return False
    return True
def load_training_data():
    import pandas as pd
    from tracker.models import Message
    qs = (Message.objects.filter(reviewed=True, ml_label__isnull=False)
        .exclude(ml_label__in=["", "unknown"])
        .values("subject", "body", "ml_label"))
    df = pd.DataFrame(list(qs))
    if df.empty:
        print("[Warning] No human-labeled messages found in database")
        return pd.DataFrame(columns=["subject", "body", "label"])
    return df.rename(columns={"ml_label": "label"})