# Environment Configuration Guide

This guide explains how to obtain the required environment variables for GmailJobTracker.

## Required Environment Variables

### 1. DJANGO_SECRET_KEY

**What it is:** A secret cryptographic key used by Django for security features (sessions, CSRF protection, etc.).

**How to get it:**

Generate a new random secret key using Python:

```powershell
# Windows PowerShell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

```bash
# Linux/macOS
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**Example output:**
```
django-insecure-xy9#2k$mz@4n8v!p7q&r3s*t6u+w-a=b%c^d_e(f)g{h|i}j
```

**Add to .env:**
```bash
DJANGO_SECRET_KEY=django-insecure-xy9#2k$mz@4n8v!p7q&r3s*t6u+w-a=b%c^d_e(f)g{h|i}j
```

**⚠️ Security Notes:**
- Keep this secret! Never share it publicly
- Never commit it to git (it's in `.gitignore`)
- Use a different key for each environment (dev, staging, production)
- Generate a new one if it's ever compromised

---

### 2. GMAIL_ROOT_FILTER_LABEL (Optional)

**What it is:** The name prefix for organizing job hunting labels in a hierarchy.

**When to use:** If you organize your Gmail labels with a parent/child structure like:
- `#job-hunt/Applied`
- `#job-hunt/Interview`
- `#job-hunt/Rejected`

Then set this to the parent label name.

**Default value:** `#job-hunt`

**How to configure:**

If you use a different label structure:
```bash
# For labels like "JobHunt/Applied", "JobHunt/Interview"
GMAIL_ROOT_FILTER_LABEL=JobHunt

# For labels like "Career/Applied", "Career/Interview"
GMAIL_ROOT_FILTER_LABEL=Career

# For the default structure "#job-hunt/..."
GMAIL_ROOT_FILTER_LABEL=#job-hunt
```

**Add to .env:**
```bash
GMAIL_ROOT_FILTER_LABEL=#job-hunt
```

**Note:** This is used by the `export_gmail_labels_filters` management command to organize exported labels.

---

## Getting Gmail API Credentials

Before you can get the label ID, you need Gmail API credentials.

### Step 1: Create Google Cloud Project

1. Go to: https://console.cloud.google.com/
2. Click "Select a project" → "New Project"
3. Enter project name: "GmailJobTracker"
4. Click "Create"

### Step 2: Enable Gmail API

1. In your project, go to "APIs & Services" → "Library"
2. Search for "Gmail API"
3. Click on "Gmail API"
4. Click "Enable"

### Step 3: Create OAuth Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure OAuth consent screen:
   - User Type: External
   - App name: GmailJobTracker
   - User support email: your email
   - Developer contact: your email
   - Click "Save and Continue"
   - Scopes: Skip (click "Save and Continue")
   - Test users: Add your Gmail address
   - Click "Save and Continue"
4. Back to credentials:
   - Application type: "Desktop app"
   - Name: "GmailJobTracker Desktop"
   - Click "Create"
5. Click "Download JSON"
6. Rename the downloaded file to `credentials.json`
7. Move it to your project's `json/` directory

### Step 4: Verify Credentials

```powershell
# Check if file exists
Test-Path json/credentials.json
# Should return: True
```

---

## Optional Environment Variables

### DEBUG

Controls Django debug mode:
```bash
DEBUG=False  # Production (recommended)
DEBUG=True   # Development (shows detailed errors)
```

### ALLOWED_HOSTS

Comma-separated list of hosts that can access your app:
```bash
ALLOWED_HOSTS=localhost,127.0.0.1,yourdomain.com
```

### DATABASE_PATH

Location of SQLite database:
```bash
DATABASE_PATH=db/job_tracker.db  # Default
```

### LOG_LEVEL

Logging verbosity:
```bash
LOG_LEVEL=INFO     # Recommended for production
LOG_LEVEL=DEBUG    # Verbose logging for troubleshooting
LOG_LEVEL=WARNING  # Only warnings and errors
```

### AUTO_REVIEW_CONFIDENCE

ML confidence threshold for auto-marking messages as reviewed:
```bash
AUTO_REVIEW_CONFIDENCE=0.85  # 85% confidence (default)
```

### ML_CONFIDENCE_THRESHOLD

Minimum ML confidence before using rule-based fallback:
```bash
ML_CONFIDENCE_THRESHOLD=0.55  # 55% confidence (default)
```

### DEFAULT_DAYS_BACK

How many days to look back when ingesting emails:
```bash
DEFAULT_DAYS_BACK=7   # Last 7 days (default)
DEFAULT_DAYS_BACK=30  # Last 30 days
```

### MAX_MESSAGES_PER_BATCH

Maximum messages to process in one ingestion run:
```bash
MAX_MESSAGES_PER_BATCH=500   # Default
```

### GHOSTED_DAYS_THRESHOLD

Days of inactivity before marking application as "ghosted":
```bash
GHOSTED_DAYS_THRESHOLD=30  # 30 days (default)
```

### GMAIL_ROOT_FILTER_LABEL

Parent label name for organizing job hunting sub-labels:
```bash
GMAIL_ROOT_FILTER_LABEL=#job-hunt  # Default
GMAIL_ROOT_FILTER_LABEL=JobHunt    # Alternative
```

---

## Complete .env Example

```bash
# Required
GMAIL_JOBHUNT_LABEL_ID=Label_1234567890123456789
DJANGO_SECRET_KEY=django-insecure-xy9#2k$mz@4n8v!p7q&r3s*t6u+w-a=b%c^d_e(f)g{h|i}j

# Gmail Configuration
GMAIL_ROOT_FILTER_LABEL=#job-hunt

# Optional (with recommended values)
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_PATH=db/job_tracker.db
LOG_LEVEL=INFO
AUTO_REVIEW_CONFIDENCE=0.85
ML_CONFIDENCE_THRESHOLD=0.55
DEFAULT_DAYS_BACK=7
MAX_MESSAGES_PER_BATCH=500
GHOSTED_DAYS_THRESHOLD=30
```

---

## Backup Your .env File

**Important:** Since `.env` is in `.gitignore`, it won't be saved to git. Always keep a backup!

### Method 1: Encrypted File

```powershell
# Windows: Use 7-Zip or similar to create password-protected archive
7z a -p env_backup.7z .env

# Store env_backup.7z in a safe location (cloud storage, password manager, etc.)
```

### Method 2: Password Manager

1. Open your password manager (1Password, LastPass, Bitwarden, etc.)
2. Create a new secure note
3. Title: "GmailJobTracker Environment Variables"
4. Paste your .env file contents
5. Save

### Method 3: Encrypted Cloud Storage

1. Save .env to encrypted cloud storage (Tresorit, SpiderOak, etc.)
2. Or use standard cloud storage with encryption (VeraCrypt container)

---

## Troubleshooting

### "GMAIL_JOBHUNT_LABEL_ID not set" error

**Solution:** Make sure you added the label ID to `.env` and it's not empty:
```bash
GMAIL_JOBHUNT_LABEL_ID=Label_1234567890123456789
```

### "django.core.exceptions.ImproperlyConfigured: The SECRET_KEY setting must not be empty"

**Solution:** Generate and add a secret key to `.env`:
```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### "gmail_auth module not found" when getting label ID

**Solution:** Make sure you're in your project directory and have credentials.json:
```powershell
cd C:\Users\kaver\code\GmailJobTracker
Test-Path json/credentials.json
```

### "Authentication failed" when listing labels

**Solution:** 
1. Delete old token: `Remove-Item json/token.json`
2. Re-authenticate when running the script
3. Make sure you added your email as a test user in Google Cloud Console

---

## Security Best Practices

1. **Never commit .env to git** - It's already in `.gitignore`
2. **Use different keys for different environments** - Dev, staging, production
3. **Rotate secrets periodically** - Generate new keys every 6-12 months
4. **Use strong, random secret keys** - Don't create them manually
5. **Limit OAuth scopes** - Only request Gmail read permissions
6. **Keep backups encrypted** - Don't store plain text in insecure locations
7. **Use environment-specific .env files** - `.env.dev`, `.env.prod`

---

## Quick Reference Commands

```powershell
# Generate Django secret key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# List Gmail labels
python -c "from gmail_auth import get_gmail_service; service = get_gmail_service(); labels = service.users().labels().list(userId='me').execute(); [print(f\"{l['name']}: {l['id']}\") for l in labels['labels']]"

# Verify .env exists
Test-Path .env

# Check credentials exist
Test-Path json/credentials.json

# Validate deployment
python validate_deployment.py
```

---

For more information, see:
- [DOCKER_DESKTOP_GUIDE.md](DOCKER_DESKTOP_GUIDE.md) - Full installation guide
- [QUICKSTART.md](QUICKSTART.md) - Quick deployment guide
- [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) - Advanced deployment options
