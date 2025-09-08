#ml_prep.py
import pandas as pd

import sqlite3


def extract_subject_body(message):
    subject = message.get("subject", "").strip()
    body = message.get("body", "").strip()
    return subject, body

def write_to_sqlite(message_id, subject, body, conn):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO email_text (message_id, subject, body)
        VALUES (?, ?, ?)
    """, (message_id, subject, body))
    conn.commit()
    
def ensure_email_text_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_text (
            message_id TEXT PRIMARY KEY,
            subject TEXT,
            body TEXT
        )
    """)
    conn.commit()
    
def load_training_data(db_path):
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
