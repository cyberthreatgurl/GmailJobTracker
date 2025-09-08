import sqlite3
from datetime import datetime

DB_PATH = 'job_tracker.db'
SCHEMA_VERSION = '1.1.0'

def init_db():
    conn = sqlite3.connect(DB_PATH)
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

    conn.commit()
    conn.close()

def insert_or_update_application(data):
    conn = sqlite3.connect(DB_PATH)
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