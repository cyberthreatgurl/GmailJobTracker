#!/usr/bin/env python3
"""
Pre-deployment validation script
Runs before Docker build to ensure everything is ready
"""

import os
import sys


def check_file_exists(filepath, description):
    """Check if a file exists"""
    if os.path.exists(filepath):
        print(f"✅ {description}: {filepath}")
        return True
    else:
        print(f"❌ {description} missing: {filepath}")
        return False


def check_env_variable(var_name):
    """Check if environment variable is set"""
    value = os.getenv(var_name)
    if value:
        print(f"✅ Environment variable {var_name} is set")
        return True
    else:
        print(f"⚠️  Environment variable {var_name} is not set")
        return False


def main():
    """Run all pre-deployment checks"""
    print("🔍 Running pre-deployment validation...\n")

    checks_passed = True

    # Required files
    print("📁 Checking required files...")
    checks_passed &= check_file_exists("Dockerfile", "Dockerfile")
    checks_passed &= check_file_exists("docker-compose.yml", "Docker Compose config")
    checks_passed &= check_file_exists("requirements.txt", "Python requirements")
    checks_passed &= check_file_exists("manage.py", "Django manage.py")
    checks_passed &= check_file_exists(".env.example", "Environment template")
    print()

    # Configuration files
    print("⚙️  Checking configuration files...")
    checks_passed &= check_file_exists("json/patterns.json", "Patterns config")
    checks_passed &= check_file_exists("json/companies.json", "Companies config")
    print()

    # Optional but recommended files
    print("📋 Checking recommended files...")
    has_env = check_file_exists(".env", "Environment file (.env)")
    has_credentials = check_file_exists("json/credentials.json", "Gmail credentials")
    print()

    # Environment variables (only if .env exists)
    if has_env:
        print("🔐 Checking environment variables...")
        check_env_variable("GMAIL_JOBHUNT_LABEL_ID")
        check_env_variable("DJANGO_SECRET_KEY")
        print()

    # Directory structure
    print("📂 Checking directory structure...")
    for dirname in ["db", "logs", "model", "json", "tracker"]:
        if os.path.isdir(dirname):
            print(f"✅ Directory exists: {dirname}/")
        else:
            print(f"⚠️  Directory missing: {dirname}/ (will be created)")
    print()

    # Docker checks
    print("🐳 Checking Docker availability...")
    import subprocess

    try:
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"✅ Docker: {result.stdout.strip()}")
        else:
            print("❌ Docker not found")
            checks_passed = False
    except Exception as e:
        print(f"❌ Docker check failed: {e}")
        checks_passed = False

    try:
        result = subprocess.run(["docker-compose", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"✅ Docker Compose: {result.stdout.strip()}")
        else:
            print("❌ Docker Compose not found")
            checks_passed = False
    except Exception as e:
        print(f"❌ Docker Compose check failed: {e}")
        checks_passed = False
    print()

    # Summary
    print("=" * 60)
    if checks_passed:
        print("✅ All critical checks passed!")
        print("\n📦 Ready for deployment!")
        print("\nNext steps:")
        print("  1. docker-compose build")
        print("  2. docker-compose up -d")
        print("  3. Access at http://localhost:8000")
        return 0
    else:
        print("❌ Some checks failed!")
        print("\n🔧 Fix the issues above before deploying.")

        if not has_env:
            print("\n💡 Tip: Copy .env.example to .env and configure it:")
            print("   cp .env.example .env")

        if not has_credentials:
            print("\n💡 Tip: Add your Gmail credentials:")
            print("   Copy credentials.json to json/credentials.json")

        return 1


if __name__ == "__main__":
    sys.exit(main())
