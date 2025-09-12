# 2025-09-09_add_company_job_index.py

import sqlite3
import re
import sys
from pathlib import Path

# Add the project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from db_helpers import build_company_job_index


DB_PATH = "job_tracker.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Add column if it doesn't exist
    cur.execute("""
        PRAGMA table_info(applications)
    """)
    cols = [row[1] for row in cur.fetchall()]
    if "company_job_index" not in cols:
        cur.execute("ALTER TABLE applications ADD COLUMN company_job_index TEXT")

    # 2. Populate column for existing rows
    cur.execute("SELECT rowid, company, job_title, job_id FROM applications")
    rows = cur.fetchall()
    for rowid, company, job_title, job_id in rows:
        idx = build_company_job_index(company, job_title, job_id)
        cur.execute("""
            UPDATE applications
            SET company_job_index = ?
            WHERE rowid = ?
        """, (idx, rowid))
    # 3. Create index for fast lookups
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_company_job_index
        ON applications(company_job_index)
    """)

    conn.commit()
    conn.close()
    print("✅ Migration complete: company_job_index added and populated.")

if __name__ == "__main__":
    migrate()