import sqlite3
import json
import pandas as pd
from datetime import datetime
import time
import re
import os
import sys
from pathlib import Path

DB_PATH = os.getenv("JOB_TRACKER_DB", "job_tracker.db")
PATTERNS_PATH = Path(__file__).parent / "patterns.json"

SCHEMA_VERSION = '1.1.0'

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
    conn = get_db_connection()

    c = conn.cursor()

    # Main applications table
    c.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            thread_id TEXT PRIMARY KEY,
            company TEXT,
            job_title TEXT,
            job_id TEXT,
            first_sent TEXT,
            response_date TEXT,
            follow_up_dates TEXT,
            rejection_date TEXT,
            interview_date TEXT,
            status TEXT,
            labels TEXT,
            notes TEXT,
            last_updated TEXT
        )
    ''')

    # Indexes for performance
    c.execute('CREATE INDEX IF NOT EXISTS idx_status ON applications(status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_company ON applications(company)')

    # Meta table for schema versioning
    c.execute('''
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ('schema_version', SCHEMA_VERSION))

    # Optional: normalized follow-up tracking (modular rollout)
    c.execute('''
        CREATE TABLE IF NOT EXISTS follow_ups (
            thread_id TEXT,
            follow_up_date TEXT,
            FOREIGN KEY(thread_id) REFERENCES applications(thread_id)
        )
    ''')
    
    # ML training table for subject + body
    c.execute('''
        CREATE TABLE IF NOT EXISTS email_text (
            message_id TEXT PRIMARY KEY,
            subject TEXT,
            body TEXT
        )
    ''')
    conn.commit()
    conn.close()

def insert_email_text(message_id, subject, body):
    
    conn = get_db_connection()
            
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO email_text (message_id, subject, body)
        VALUES (?, ?, ?)
    ''', (message_id, subject, body))
    conn.commit()
    conn.close()

def load_training_data():
    conn = sqlite3.connect(DB_PATH)
    query = '''
        SELECT e.message_id, e.subject, e.body, a.company
        FROM email_text e
        JOIN applications a ON e.message_id = a.thread_id
        WHERE a.company IS NOT NULL AND a.company != ''
    '''
    df = pd.read_sql_query(query, conn)
    conn.close()

    # --- Normalize company names ---
    def normalize_company(name):
        name = name.strip()
        # If there's an "at" or "@" followed by company, keep only the company
        match = re.search(r'\b(?:at|@)\s+(.+)$', name, flags=re.IGNORECASE)
        if match:
            name = match.group(1)
        return name.strip()

    df['company'] = df['company'].apply(normalize_company)

    # --- Remove obvious non-company noise ---
    df = df[df['company'].str.len() > 3]
    df = df[~df['company'].str.contains(
        r'thank you|evaluate|job|sr|intelligence|lead engineer',
        case=False
    )]

    # --- Optional: Apply ignore patterns from patterns.json ---
    if PATTERNS_PATH.exists():
        with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
            patterns = json.load(f)
        ignore_patterns = [p.lower() for p in patterns.get("ignore", [])]
        mask_ignore = df['subject'].str.lower().apply(
            lambda subj: any(pat in subj for pat in ignore_patterns)
        )
        df = df[~mask_ignore]

    # --- Remove likely personal names ---
    personal_name_regex = re.compile(r'^[A-Z][a-z]+ [A-Z][a-z]+$')
    corp_suffix_regex = re.compile(
        r'(Inc|LLC|Ltd|Technologies|Systems|Group|Corp|Company|Co\.|PLC)$', re.I
    )

    def is_personal_name(name):
        return bool(personal_name_regex.match(name)) and not corp_suffix_regex.search(name)

    df = df[~df['company'].apply(is_personal_name)]

    # --- Final safeguard ---
    unique_companies = df['company'].nunique()
    if unique_companies < 2:
        raise ValueError(
            f"🚫 Not enough unique companies after cleaning ({unique_companies} found) — aborting training."
        )

    return df

def insert_or_update_application(data):
    conn = get_db_connection()

    c = conn.cursor()

    # Add last_updated timestamp
    data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    c.execute('''
        INSERT OR REPLACE INTO applications (
            thread_id, company, job_title, job_id, first_sent,
            response_date, follow_up_dates, rejection_date,
            interview_date, status, labels, notes, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data['thread_id'],
        data.get('company', ''),
        data.get('job_title', ''),
        data.get('job_id', ''),
        data.get('first_sent', ''),
        data.get('response_date', ''),
        data.get('follow_up_dates', ''),
        data.get('rejection_date', ''),
        data.get('interview_date', ''),
        data.get('status', ''),
        data.get('labels', ''),
        data.get('notes', ''),
        data['last_updated']
    ))

    conn.commit()
    conn.close()