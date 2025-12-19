import argparse
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "job_tracker.db"
BACKUP_PATH = BASE_DIR / "job_tracker.db.bak"
MIGRATIONS_DIR = BASE_DIR / "tracker" / "migrations"
MODEL_DIR = BASE_DIR / "model"


def run(cmd, dry_run=False):
    print(f"🔧 Running: {cmd}")
    if not dry_run:
        subprocess.run(cmd, shell=True, check=True, cwd=BASE_DIR)


def delete_db(dry_run=False, backup=False):
    if DB_PATH.exists():
        if backup:
            shutil.copy(DB_PATH, BACKUP_PATH)
            print(f"Backed up database to {BACKUP_PATH.name}")
        if dry_run:
            print(f"Would delete {DB_PATH.name}")
        else:
            DB_PATH.unlink()
            print(f"Deleted {DB_PATH.name}")
    else:
        print("No database file found — skipping.")


def clean_migrations(dry_run=False):
    for file in MIGRATIONS_DIR.glob("*.py"):
        if file.name != "__init__.py":
            if dry_run:
                print(f"Would delete {file.name}")
            else:
                file.unlink()
    pycache = MIGRATIONS_DIR / "__pycache__"
    if pycache.exists():
        if dry_run:
            print(f"Would delete {pycache}")
        else:
            shutil.rmtree(pycache)
    print("Migrations cleaned.")


def preserve_models():
    if MODEL_DIR.exists():
        print("ML model files preserved:")
        for f in MODEL_DIR.glob("*.pkl"):
            print(f"   - {f.name}")
    else:
        print("No model directory found — skipping.")


def rebuild(dry_run=False):
    run("python manage.py makemigrations tracker", dry_run)
    run("python manage.py migrate", dry_run)


def show_help():
    help_text = (
        "Usage: python scripts/reset_tracker.py [--dry-run] [--backup-db] [--help]\n\n"
        "Options:\n"
        "  --dry-run     Preview actions without executing them\n"
        "  --backup-db   Save a copy of job_tracker.db before deletion\n"
        "  --help        Show this help message\n"
    )
    print(help_text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup-db", action="store_true")
    parser.add_argument("--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        show_help()
    else:
        print("🚀 Resetting GmailJobTracker environment...")
        delete_db(dry_run=args.dry_run, backup=args.backup_db)
        clean_migrations(dry_run=args.dry_run)
        preserve_models()
        rebuild(dry_run=args.dry_run)
        print("✅ Reset complete." if not args.dry_run else "🧪 Dry run complete.")
