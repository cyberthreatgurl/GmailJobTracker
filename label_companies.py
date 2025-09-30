# label_companies.py
# Script to label companies for job applications with missing or generic company names.


import sqlite3
import csv
from pathlib import Path

DB_PATH = "job_tracker.db"
TRAINING_EXPORT = "labeled_companies.csv"

def label_companies():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT a.thread_id, a.subject, e.body, e.sender
        FROM applications a
        JOIN email_text e ON a.thread_id = e.msg_id
        WHERE a.company IS NULL
           OR a.company = ''
           OR LOWER(a.company) = 'intel'
    """)
    rows = cur.fetchall()

    if not rows:
        print("✅ No unlabeled companies found.")
        return

    # Prepare CSV export
    export_exists = Path(TRAINING_EXPORT).exists()
    with open(TRAINING_EXPORT, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if not export_exists:
            writer.writerow(["thread_id", "subject", "sender", "company"])

        for thread_id, subject, body, sender in rows:
            print("\n----------------------------------------")
            print(f"Subject: {subject}")
            print(f"Sender: {sender}")
            label = input("Enter company (or leave blank to skip): ").strip()
            if label:
                # Update DB
                cur.execute("""
                    UPDATE applications
                    SET company = ?
                    WHERE thread_id = ?
                """, (label, thread_id))
                conn.commit()

                # Append to CSV for ML training
                writer.writerow([thread_id, subject, sender, label])

    conn.close()
    print("✅ Labeling complete.")

if __name__ == "__main__":
    label_companies()
