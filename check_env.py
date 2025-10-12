import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

REQUIRED_FILES = {
    "SQLite DB": BASE_DIR / "job_tracker.db",
    "patterns.json": BASE_DIR / "patterns.json",
    "companies.json": BASE_DIR / "companies.json",
    "message_classifier.pkl": BASE_DIR / "model" / "message_classifier.pkl",
    "message_vectorizer.pkl": BASE_DIR / "model" / "message_vectorizer.pkl",
    "message_label_encoder.pkl": BASE_DIR / "model" / "message_label_encoder.pkl",
}

OPTIONAL_FILES = {
    "labeled_subjects.csv": BASE_DIR / "data" / "labeled_subjects.csv",
    "alias_candidates.json": BASE_DIR / "alias_candidates.json",
    "company_aliases.json": BASE_DIR / "company_aliases.json",
}

def check_file(path, label, required=True):
    if path.exists():
        print(f"✅ {label}: Found at {path}")
    else:
        status = "❌ MISSING" if required else "⚠️ Optional but missing"
        print(f"{status}: {label} ({path})")

def check_django_migrations():
    print("\n🧱 Django Migrations:")
    try:
        result = subprocess.run(
            ["python", "manage.py", "showmigrations", "--plan"],
            capture_output=True,
            text=True,
            check=True
        )
        print("✅ Migration plan retrieved.")
        print(result.stdout)
    except Exception as e:
        print(f"❌ Failed to check migrations: {e}")

def check_oauth_credentials():
    print("\n🔐 OAuth Credentials:")
    token_path = BASE_DIR / "token.json"
    creds_path = BASE_DIR / "credentials.json"
    check_file(token_path, "token.json", required=False)
    check_file(creds_path, "credentials.json", required=False)

def check_directory_permissions():
    print("\n📂 Directory Permissions:")
    writable_dirs = ["model", "data", "."]
    for d in writable_dirs:
        path = BASE_DIR / d
        if os.access(path, os.W_OK):
            print(f"✅ Writable: {path}")
        else:
            print(f"❌ Not writable: {path}")

def check_git_status():
    print("\n🔧 Git Status:")
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        print(f"✅ Git branch: {branch}")
        print(f"✅ Latest commit: {commit}")
    except Exception as e:
        print(f"⚠️ Git status unavailable: {e}")

def main():
    print("🔍 Checking environment readiness...\n")

    print("📦 Required files:")
    for label, path in REQUIRED_FILES.items():
        check_file(path, label, required=True)

    print("\n📁 Optional files:")
    for label, path in OPTIONAL_FILES.items():
        check_file(path, label, required=False)

    check_django_migrations()
    check_oauth_credentials()
    check_directory_permissions()
    check_git_status()
    check_detect_secrets()

    print("\n✅ Done. Review any ❌ or ⚠️ items above to complete setup.")

def check_detect_secrets():
    print("\n🔒 Secret Scanning (detect-secrets):")
    baseline_path = BASE_DIR / ".secrets.baseline"

    if baseline_path.exists():
        print(f"✅ .secrets.baseline found at {baseline_path}")
        try:
            result = subprocess.run(
                ["detect-secrets", "scan", "--baseline", str(baseline_path)],
                capture_output=True,
                text=True,
                check=True
            )
            print("✅ Scan completed. No new secrets detected.")
        except subprocess.CalledProcessError as e:
            print("❌ Secret scan failed or secrets detected.")
            print(e.stdout or e.stderr)
    else:
        print("⚠️ .secrets.baseline not found. Generating new baseline...")
        try:
            result = subprocess.run(
                ["detect-secrets", "scan", "--all-files", "--output", str(baseline_path)],
                capture_output=True,
                text=True,
                check=True
            )
            print("✅ New .secrets.baseline created.")
        except subprocess.CalledProcessError as e:
            print("❌ Failed to create .secrets.baseline.")
            print(e.stdout or e.stderr)
            
if __name__ == "__main__":
    main()