# db.py
#
import sqlite3
import json
import pandas as pd
from datetime import datetime, date
import time
import re
import os
import sys
from pathlib import Path

DB_PATH = os.getenv("JOB_TRACKER_DB", "job_tracker.db")
PATTERNS_PATH = Path(__file__).parent / "patterns.json"

SCHEMA_VERSION = '1.1.0'

# --- Apply is_valid_company() filter globally ---
def is_valid_company(name):
    name = name.strip()
    if not name or len(name.split()) > 8:
        return False
    if re.search(r'\b(application|interview|position|role|job|resume|thank you|your)\b', name, re.I):
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
    conn = get_db_connection()

    c = conn.cursor()

    # Main applications table
    c.execute('''
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
    ''')

    # Indexes for performance
    c.execute('CREATE INDEX IF NOT EXISTS idx_status ON applications(status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_company ON applications(company)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_company_job_index ON applications(company_job_index)')
    
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

    # Company
    c.execute('''
        CREATE TABLE IF NOT EXISTS tracker_company (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            domain TEXT,
            first_contact TEXT NOT NULL,
            last_contact TEXT NOT NULL
        )
    ''')

    # Application
    c.execute('''
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
    ''')

    # Message
    c.execute('''
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
    ''')

    # IgnoredMessage
    c.execute('''
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
    ''')

    # IngestionStats
    c.execute('''
        CREATE TABLE IF NOT EXISTS tracker_ingestionstats (
            date TEXT PRIMARY KEY,
            total_fetched INTEGER DEFAULT 0,
            total_inserted INTEGER DEFAULT 0,
            total_ignored INTEGER DEFAULT 0,
            total_skipped INTEGER DEFAULT 0
        )
    ''')

    # Ensure today's row exists
    today = date.today().isoformat()
    c.execute('INSERT OR IGNORE INTO tracker_ingestionstats (date) VALUES (?)', (today,))

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

    if df.empty:
        raise ValueError("🚫 No training data found in applications/email_text")

    # --- Normalize company names ---
    def normalize_company(name):
        name = name.strip().rstrip(",.")
        match = re.search(r'\b(?:at|@)\s+(.+)$', name, flags=re.IGNORECASE)
        if match:
            name = match.group(1)
        return name.strip()

    df['company'] = df['company'].apply(normalize_company)

    # --- Optional: Apply alias mappings and ignore patterns from patterns.json ---
    if PATTERNS_PATH.exists():
        with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
            patterns = json.load(f)

        alias_map = patterns.get("aliases", {})
        if alias_map:
            print(f"🔄 Applying {len(alias_map)} company alias mappings from patterns.json")
            df['company'] = df['company'].replace(alias_map)

        ignore_patterns = [p.lower() for p in patterns.get("ignore", [])]
        if ignore_patterns:
            mask_ignore = df['subject'].str.lower().apply(
                lambda subj: any(pat in subj for pat in ignore_patterns)
            )
            df = df[~mask_ignore]

    # --- Remove obvious non-company noise ---
    df = df[df['company'].str.len() > 3]
    df = df[~df['company'].str.contains(
        r'thank you|evaluate|job|sr|intelligence|lead engineer',
        case=False
    )]

    # --- Remove likely personal names ---
    personal_name_regex = re.compile(r'^[A-Z][a-z]+ [A-Z][a-z]+$')
    corp_suffix_regex = re.compile(
        r'(Inc|LLC|Ltd|Technologies|Systems|Group|Corp|Company|Co\.|PLC)$', re.I
    )

    def is_personal_name(name):
        return bool(personal_name_regex.match(name)) and not corp_suffix_regex.search(name)

    df = df[~df['company'].apply(is_personal_name)]

    # --- Global validity filter ---
    invalids = df[~df['company'].apply(is_valid_company)]
    if not invalids.empty:
        print("🧹 Dropped invalid company labels (global filter):")
        print(invalids['company'].value_counts())

    df = df[df['company'].apply(is_valid_company)]

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

    # Normalize follow_up_dates and labels to strings
    follow_up_raw = data.get('follow_up_dates', [])
    data['follow_up_dates'] = ", ".join(follow_up_raw) if isinstance(follow_up_raw, list) else str(follow_up_raw)

    labels_raw = data.get('labels', [])
    data['labels'] = ", ".join(labels_raw) if isinstance(labels_raw, list) else str(labels_raw)

    c.execute('''
        INSERT OR REPLACE INTO applications (
            thread_id, company, predicted_company, job_title, job_id, first_sent,
            response_date, follow_up_dates, rejection_date,
            interview_date, status, labels, subject, sender, sender_domain,
            company_job_index, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data['thread_id'],
        data.get('company', ''),
        data.get('predicted_company', ''),
        data.get('job_title', ''),
        data.get('job_id', ''),
        data.get('first_sent', ''),
        data.get('response_date', ''),
        data.get('follow_up_dates', ''),
        data.get('rejection_date', ''),
        data.get('interview_date', ''),
        data.get('status', ''),
        data.get('labels', ''),
        data.get('subject', ''),
        data.get('sender', ''),
        data.get('sender_domain', ''),
        data.get('company_job_index', ''),
        data['last_updated']
    ))

    conn.commit()
    conn.close()