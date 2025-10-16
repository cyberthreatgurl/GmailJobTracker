"""Legacy wrapper — use 'python manage.py ingest_gmail' instead."""
import sys
import subprocess


if __name__ == "__main__":
    print("main.py is deprecated. Use: python manage.py ingest_gmail")
    # Pass args through to Django command
    cmd = ["python", "manage.py", "ingest_gmail"] + sys.argv[1:]
    sys.exit(subprocess.call(cmd))
