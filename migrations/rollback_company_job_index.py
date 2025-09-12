
import sqlite3

DB_PATH = "job_tracker.db"

def rollback():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Drop index if exists
    cur.execute("DROP INDEX IF EXISTS idx_company_job_index")

    # SQLite can't drop columns easily — so we leave the column in place
    # but clear its data if needed
    cur.execute("UPDATE applications SET company_job_index = NULL")

    conn.commit()
    conn.close()
    print("♻️ Rollback complete: index dropped, column cleared.")

if __name__ == "__main__":
    rollback()