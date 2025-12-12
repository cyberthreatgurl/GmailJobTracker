"""Database operations and utilities for job tracker SQLite database."""
# db.py
#
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

DB_PATH = os.getenv("JOB_TRACKER_DB", "db/job_tracker.db")
PATTERNS_PATH = Path(__file__).parent / "json/patterns.json"
COMPANIES_PATH = Path(__file__).parent / "json/companies.json"
SCHEMA_VERSION = "2.0.0"


# --- Apply is_valid_company() filter globally ---
def is_valid_company(name):
    """Check if a company name passes basic validation rules."""
    name = name.strip()
    if not name or len(name.split()) > 8:
        return False
    if re.search(
        r"\b(application|interview|position|role|job|resume|thank you|your)\b",
        name,
        re.I,
    ):
        return False
    return True


def get_db_connection(retries=3, delay=2):
    """
    Safely open a SQLite connection with retry logic for locked databases.
    Exits gracefully if the database is missing or inaccessible.
    """
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(DB_PATH)
            return conn
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg:
                print(f"⚠️ Attempt {attempt+1}: Database is locked. Retrying in {delay} seconds...")
                time.sleep(delay)
            elif "unable to open database file" in error_msg:
                print("❌ Database file not found or inaccessible. Check DB_PATH and permissions.")
                sys.exit(1)
            else:
                print(f"❌ Unexpected SQLite error: {e}")
                sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected error while opening database: {e}")
            sys.exit(1)

    print("❌ Failed to acquire database lock after multiple attempts.")
    sys.exit(1)


def init_db():
    """Initialize the database schema and tables."""
    conn = get_db_connection()

    c = conn.cursor()

    # Main applications table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            thread_id TEXT PRIMARY KEY,
            company TEXT,
            predicted_company TEXT,
            job_title TEXT,
            job_id TEXT,
            first_sent TEXT,
            response_date TEXT,
            follow_up_dates TEXT,
            rejection_date TEXT,
            interview_date TEXT,
            status TEXT,
            labels TEXT,
            subject TEXT,
            sender TEXT,
            sender_domain TEXT,
            company_job_index TEXT,
            last_updated TEXT
        )
    """
    )

    # Indexes for performance
    c.execute("CREATE INDEX IF NOT EXISTS idx_status ON applications(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_company ON applications(company)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_company_job_index ON applications(company_job_index)")

    # Meta table for schema versioning
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """
    )
    c.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", SCHEMA_VERSION),
    )

    # Optional: normalized follow-up tracking (modular rollout)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS follow_ups (
            thread_id TEXT,
            follow_up_date TEXT,
            FOREIGN KEY(thread_id) REFERENCES applications(thread_id)
        )
    """
    )

    # ML training table for subject + body
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS email_text (
            message_id TEXT PRIMARY KEY,
            subject TEXT,
            body TEXT
        )
    """
    )

    # Company
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tracker_company (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            domain TEXT,
            first_contact TEXT NOT NULL,
            last_contact TEXT NOT NULL
        )
    """
    )

    # Application
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tracker_application (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT UNIQUE NOT NULL,
            company_source TEXT,
            company_id INTEGER NOT NULL REFERENCES tracker_company(id) ON DELETE CASCADE,
            job_title TEXT NOT NULL,
            status TEXT NOT NULL,
            sent_date TEXT NOT NULL,
            rejection_date TEXT,
            interview_date TEXT,
            ml_label TEXT,
            ml_confidence REAL,
            reviewed INTEGER DEFAULT 0
        )
    """
    )

    # Message
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tracker_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER REFERENCES tracker_company(id) ON DELETE SET NULL,
            sender TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            msg_id TEXT UNIQUE NOT NULL,
            thread_id TEXT NOT NULL,
            ml_label TEXT,
            confidence REAL,
            reviewed INTEGER DEFAULT 0
        )
    """
    )

    # IgnoredMessage
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tracker_ignoredmessage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id TEXT UNIQUE NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            sender TEXT NOT NULL,
            sender_domain TEXT NOT NULL,
            date TEXT NOT NULL,
            reason TEXT NOT NULL,
            logged_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # IngestionStats
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tracker_ingestionstats (
            date TEXT PRIMARY KEY,
            total_fetched INTEGER DEFAULT 0,
            total_inserted INTEGER DEFAULT 0,
            total_ignored INTEGER DEFAULT 0,
            total_skipped INTEGER DEFAULT 0
        )
    """
    )

    # Ensure today's row exists
    today = date.today().isoformat()
    c.execute("INSERT OR IGNORE INTO tracker_ingestionstats (date) VALUES (?)", (today,))

    conn.commit()
    conn.close()


def insert_email_text(message_id, subject, body):
    """Insert message text into email_texts table for search/analysis."""
    conn = get_db_connection()

    c = conn.cursor()
    
    # Ensure table exists (in case init_db wasn't run)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS email_text (
            message_id TEXT PRIMARY KEY,
            subject TEXT,
            body TEXT
        )
        """
    )
    
    c.execute(
        """
        INSERT OR REPLACE INTO email_text (message_id, subject, body)
        VALUES (?, ?, ?)
    """,
        (message_id, subject, body),
    )
    conn.commit()
    conn.close()


def load_training_data():
    """Load labeled messages from Django Message model."""
    import pandas as pd

    from tracker.models import Message

    # Get all messages with manual labels (where reviewed=True and ml_label is set)
    qs = (
        Message.objects.filter(reviewed=True, ml_label__isnull=False)
        .exclude(ml_label__in=["", "unknown"])
        .values("subject", "body", "ml_label")
    )

    df = pd.DataFrame(list(qs))

    if df.empty:
        print("[Warning] No human-labeled messages found in database")
        return pd.DataFrame(columns=["subject", "body", "label"])

    # Rename ml_label to label for consistency with training script
    df = df.rename(columns={"ml_label": "label"})

    print(f"[OK] Loaded {len(df)} human-labeled messages from database")
    return df


def insert_or_update_application(data):
    """Insert or update a job application record in the database."""
    conn = get_db_connection()
    c = conn.cursor()

    # Add last_updated timestamp
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Normalize follow_up_dates and labels to strings
    follow_up_raw = data.get("follow_up_dates", [])
    data["follow_up_dates"] = ", ".join(follow_up_raw) if isinstance(follow_up_raw, list) else str(follow_up_raw)

    labels_raw = data.get("labels", [])
    data["labels"] = ", ".join(labels_raw) if isinstance(labels_raw, list) else str(labels_raw)

    c.execute(
        """
        INSERT OR REPLACE INTO applications (
            thread_id, company, predicted_company, job_title, job_id, first_sent,
            response_date, follow_up_dates, rejection_date,
            interview_date, status, labels, subject, sender, sender_domain,
            company_job_index, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            data["thread_id"],
            data.get("company", ""),
            data.get("predicted_company", ""),
            data.get("job_title", ""),
            data.get("job_id", ""),
            data.get("first_sent", ""),
            data.get("response_date", ""),
            data.get("follow_up_dates", ""),
            data.get("rejection_date", ""),
            data.get("interview_date", ""),
            data.get("status", ""),
            data.get("labels", ""),
            data.get("subject", ""),
            data.get("sender", ""),
            data.get("sender_domain", ""),
            data.get("company_job_index", ""),
            data["last_updated"],
        ),
    )

    conn.commit()
    conn.close()
