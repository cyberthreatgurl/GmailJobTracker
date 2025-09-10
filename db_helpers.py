import sqlite3
from datetime import datetime, timedelta

def get_application_by_sender(sender_email, sender_domain):
    """
    Look up the most recent application for this sender email or domain.
    Returns a dict with application fields, or None if not found.
    """
    conn = sqlite3.connect("job_tracker.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # First try exact email match
    cur.execute("""
        SELECT * FROM applications
        WHERE sender = ?
        ORDER BY first_sent DESC
        LIMIT 1
    """, (sender_email,))
    row = cur.fetchone()

    # If no exact match, try domain match
    if not row:
        cur.execute("""
            SELECT * FROM applications
            WHERE sender_domain = ?
            ORDER BY first_sent DESC
            LIMIT 1
        """, (sender_domain,))
        row = cur.fetchone()

    conn.close()
    return dict(row) if row else None