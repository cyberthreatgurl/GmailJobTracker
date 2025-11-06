"""
Database initialization script for GmailJobTracker.
Creates directories, runs migrations, and sets up initial configuration.
"""

import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()


def create_directories():
    """Create required directories if they don't exist."""
    print("📁 Creating required directories...")
    directories = [
        BASE_DIR / "db",
        BASE_DIR / "logs",
        BASE_DIR / "model",
        BASE_DIR / "json",
    ]

    for directory in directories:
        directory.mkdir(exist_ok=True)
        print(f"   ✓ {directory}")


def copy_example_configs():
    """Copy example configuration files if they don't exist."""
    print("\n📋 Setting up configuration files...")

    configs = [
        (".env.example", ".env"),
        ("json/patterns.json.example", "json/patterns.json"),
        ("json/companies.json.example", "json/companies.json"),
    ]

    for example, target in configs:
        example_path = BASE_DIR / example
        target_path = BASE_DIR / target

        if target_path.exists():
            print(f"   ⚠️  {target} already exists, skipping")
        elif example_path.exists():
            shutil.copy(example_path, target_path)
            print(f"   ✓ Copied {example} → {target}")
        else:
            print(f"   ⚠️  {example} not found, will need manual setup")


def run_migrations():
    """Run Django migrations."""
    print("\n🗄️  Running database migrations...")
    try:
        subprocess.run([sys.executable, "manage.py", "migrate"], check=True, cwd=BASE_DIR)
        print("   ✓ Migrations completed successfully")
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Migration failed: {e}")
        return False
    return True


def create_superuser():
    """Prompt user to create Django superuser."""
    print("\n👤 Creating Django superuser account...")
    print("   (This account is for admin panel access)")

    try:
        subprocess.run([sys.executable, "manage.py", "createsuperuser"], check=True, cwd=BASE_DIR)
        print("   ✓ Superuser created successfully")
    except subprocess.CalledProcessError:
        print("   ⚠️  Superuser creation cancelled or failed")
    except KeyboardInterrupt:
        print("\n   ⚠️  Superuser creation cancelled")


def check_spacy_model():
    """Check if spaCy English model is installed."""
    print("\n🧠 Checking spaCy language model...")
    try:
        import spacy

        spacy.load("en_core_web_sm")
        print("   ✓ spaCy model 'en_core_web_sm' is installed")
        return True
    except OSError:
        print("   ❌ spaCy model 'en_core_web_sm' not found")
        print("\n   Run: python -m spacy download en_core_web_sm")
        return False


def display_next_steps():
    """Display next steps after initialization."""
    print("\n" + "=" * 60)
    print("✅ Database initialization complete!")
    print("=" * 60)

    print("\n📝 Next Steps:")

    # Check for credentials
    creds_path = BASE_DIR / "json" / "credentials.json"
    if not creds_path.exists():
        print("\n   1. Set up Gmail OAuth:")
        print("      - See INSTALL.md section 4 for detailed instructions")
        print("      - Place credentials.json in json/ directory")

    # Check for .env configuration
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        print("\n   2. Configure environment variables:")
        print("      - Edit .env file")
        print("      - Add GMAIL_JOBHUNT_LABEL_ID (see INSTALL.md)")
    else:
        with open(env_path) as f:
            content = f.read()
            if "GMAIL_JOBHUNT_LABEL_ID=" in content and "Label_" not in content:
                print("\n   2. Configure Gmail label:")
                print("      - Edit .env and set GMAIL_JOBHUNT_LABEL_ID")

    print("\n   3. Run environment check:")
    print("      python check_env.py")

    print("\n   4. Ingest Gmail messages:")
    print("      python manage.py ingest_gmail --days-back 7")

    print("\n   5. Start dashboard:")
    print("      python manage.py runserver")
    print("      Visit: http://127.0.0.1:8000/")

    print("\n📖 Full documentation: INSTALL.md")
    print()


def main():
    print("🚀 GmailJobTracker - Database Initialization")
    print("=" * 60 + "\n")

    # Create directories
    create_directories()

    # Copy example configs
    copy_example_configs()

    # Check spaCy model
    spacy_ok = check_spacy_model()

    # Run migrations
    migrations_ok = run_migrations()

    if not migrations_ok:
        print("\n❌ Database initialization failed.")
        print("   Check error messages above and try again.")
        sys.exit(1)

    # Create superuser
    try:
        create_superuser()
    except Exception as e:
        print(f"   ⚠️  Error during superuser creation: {e}")

    # Display next steps
    display_next_steps()


if __name__ == "__main__":
    main()
