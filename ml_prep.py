"""Utilities for preparing training data for machine learning models."""
# ml_prep.py
import sqlite3

import pandas as pd


def extract_subject_body(message):
    """Extract subject and body fields from a message dict."""
    subject = message.get("subject", "").strip()
    body = message.get("body", "").strip()
    return subject, body


def write_to_sqlite(message_id, subject, body, conn):
    """Write message text data to SQLite email_text table."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO email_text (message_id, subject, body)
        VALUES (?, ?, ?)
    """,
        (message_id, subject, body),
    )
    conn.commit()


def ensure_email_text_table(conn):
    """Create email_text table if it doesn't exist."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS email_text (
            message_id TEXT PRIMARY KEY,
            subject TEXT,
            body TEXT
        )
    """
    )
    conn.commit()


def load_training_data(db_path):
    """Load training data from database (email text + labeled companies)."""
    conn = sqlite3.connect(db_path)
    query = """
        SELECT e.message_id, e.subject, e.body, a.company
        FROM email_text e
        JOIN applications a ON e.message_id = a.message_id
        WHERE a.company IS NOT NULL AND a.company != ''
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df
