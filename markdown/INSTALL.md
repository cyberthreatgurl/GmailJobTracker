# GmailJobTracker - Installation Guide

## Prerequisites

- **Python 3.10+** (recommended: Python 3.12)
- **Git** (for cloning the repository)
- **Gmail Account** with API access enabled
- **Windows/Linux/macOS** (tested on Windows 11, WSL2, Ubuntu 22.04)

## Quick Start (5 Minutes)

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/GmailJobTracker.git
cd GmailJobTracker

# 2. Create virtual environment
python -m venv .venv

# Windows PowerShell
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Download spaCy language model
python -m spacy download en_core_web_sm

# 5. Copy example configuration files
cp .env.example .env
cp json/patterns.json.example json/patterns.json
cp json/companies.json.example json/companies.json

# 6. Set up Gmail OAuth (see section below)
# Place your credentials.json in json/ directory

# 7. Initialize database
python init_db.py

# 8. Run initial environment check
python check_env.py

# 9. Ingest Gmail messages (last 7 days)
python manage.py ingest_gmail --days-back 7

# 10. Start dashboard
python manage.py runserver
```

Visit: <http://127.0.0.1:8000/>

## Detailed Installation Steps

### 1. Python Environment Setup

**Check Python version:**

```bash
python --version  # Should be 3.10 or higher
```

**Create isolated virtual environment:**

```bash
python -m venv .venv
```

**Activate virtual environment:**

- **Windows PowerShell:** `.venv\Scripts\activate`
- **Windows CMD:** `.venv\Scripts\activate.bat`
- **Linux/macOS:** `source .venv/bin/activate`

You should see `(.venv)` prefix in your terminal prompt.

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Expected packages:**

- Django 5.2.6
- scikit-learn 1.7.1
- spaCy 3.8.0
- BeautifulSoup4 4.12.3
- google-api-python-client 2.125.0
- pandas, numpy, and ML utilities

**Download spaCy English model:**

```bash
python -m spacy download en_core_web_sm
```

### 3. Configuration Files

**Copy example files:**

```bash
# Windows PowerShell
cp .env.example .env
cp json\patterns.json.example json\patterns.json
cp json\companies.json.example json\companies.json

# Linux/macOS
cp .env.example .env
cp json/patterns.json.example json/patterns.json
cp json/companies.json.example json/companies.json
```

**Edit `.env` file (optional):**

```bash
# Optional: Django secret key (will auto-generate if missing)
DJANGO_SECRET_KEY=your-secret-key-here

# Optional: Debug mode (default: True for development)
DEBUG=True

# Optional: Your email to exclude your replies from statistics
USER_EMAIL_ADDRESS=your-email@gmail.com
```

> **Note:** As of November 2025, Gmail labels are no longer required! The system now searches your entire Gmail account automatically.

### 4. Gmail OAuth Setup

**Detailed guide:** See `markdown/GMAIL_OAUTH_SETUP.md`

**Quick steps:**

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project: "GmailJobTracker"
3. Enable **Gmail API**
4. Configure OAuth consent screen:
   - User Type: External
   - App name: GmailJobTracker
   - Scopes: `gmail.readonly`
5. Create OAuth 2.0 credentials:
   - Application type: Desktop app
   - Download `credentials.json`
6. Place `credentials.json` in `json/` directory

That's it! No need to create or configure Gmail labels.

**First-time OAuth flow:**

When you run ingestion the first time, a browser window will open:

1. Sign in to your Gmail account
2. Click "Allow" to grant read-only access
3. `token.json` will be saved automatically

### 5. Database Initialization

**Run initialization script:**

```bash
python init_db.py
```

This will:

- Create required directories (`db/`, `logs/`, `model/`)
- Run Django migrations
- Create superuser account (you'll be prompted for username/password)
- Initialize default ML model

**Manual alternative:**

```bash
# Create directories
mkdir -p db logs model json

# Run Django migrations
python manage.py migrate

# Initialize legacy database tables
python manage.py init_legacy_db

# Create superuser
python manage.py createsuperuser
```

### 6. Environment Verification

**Run comprehensive checks:**

```bash
python check_env.py
```

Expected output:

```
✓ Required files: patterns.json, companies.json
✓ All root JSON files are valid
✓ Django migrations: All applied
✓ OAuth credentials: credentials.json found
✓ Directory permissions: All writable
✓ Secret scanning: No secrets detected
```

**Fix common issues:**

- Missing `credentials.json` → Complete Gmail OAuth setup (step 4)
- Invalid JSON syntax → Check JSON files for trailing commas, quotes
- Migration errors → Delete `db.sqlite3` and re-run `python manage.py migrate`

### 7. Initial Gmail Ingestion

**Ingest last 7 days:**

```bash
python manage.py ingest_gmail --days-back 7
```

**Ingest specific date range:**

```bash
python manage.py ingest_gmail --after 2025/01/01 --before 2025/03/31
```

**Monitor output:**

```
Authenticating with Gmail API...
Fetching messages with label: JobHunt (Label_123456789)
Processing message 1/50...
✓ Company: Acme Corp (domain: acmecorp.com, confidence: 95%)
✓ Label: job_application (confidence: 88%, auto-reviewed)
Ingestion complete: 45 inserted, 5 ignored (noise)
```

### 8. Start Dashboard

```bash
python manage.py runserver
```

**Access points:**

- Dashboard: <http://127.0.0.1:8000/>
- Admin panel: <http://127.0.0.1:8000/admin/>
- Label messages: <http://127.0.0.1:8000/tracker/label_messages/>
- Metrics: <http://127.0.0.1:8000/tracker/metrics/>

**Login with superuser credentials** created in step 5.

## Post-Installation Tasks

### 1. Label Messages for Training

1. Visit: <http://127.0.0.1:8000/tracker/label_messages/>
2. Select 20-50 messages using checkboxes
3. Choose correct label from dropdown (noise, interview_invite, job_application, rejection, etc.)
4. Click "Apply Label to Selected"
5. Model retrains automatically after every 20 labels

### 2. Verify Company Resolution

1. Visit: <http://127.0.0.1:8000/admin/tracker/unresolvedcompany/>
2. Manually assign companies to unresolved messages
3. Add company domain mappings to `json/companies.json`:

   ```json
   {
     "domain_to_company": {
       "greenhouse.io": "Greenhouse",
       "myworkdayjobs.com": "Workday"
     }
   }
   ```

4. Re-ingest: `python manage.py ingest_gmail --force --days-back 30`

### 3. Customize Configuration

**Edit `json/patterns.json`:**

- Add regex patterns for new message types
- Update ATS domain mappings
- Adjust ignore rules for noise filtering

**Edit `json/companies.json`:**

- Add known companies to whitelist
- Map ATS domains to canonical company names
- Configure company name normalization rules

### 4. Schedule Automatic Ingestion

**Windows Task Scheduler:**

```powershell
# Daily sync at 9 AM
schtasks /create /tn "GmailJobTracker Sync" /tr "C:\path\to\.venv\Scripts\python.exe C:\path\to\GmailJobTracker\manage.py ingest_gmail --days-back 1" /sc daily /st 09:00
```

**Linux/macOS cron:**

```bash
# Add to crontab (crontab -e)
0 9 * * * cd /path/to/GmailJobTracker && .venv/bin/python manage.py ingest_gmail --days-back 1
```

## Troubleshooting

### OAuth Token Expired

**Error:** `RefreshError: invalid_grant`
**Solution:**

```bash
rm json/token.json
python manage.py ingest_gmail --days-back 1  # Re-authenticate
```

### Low Classification Confidence

**Issue:** Messages show <50% confidence
**Solution:**

1. Label more training data (aim for 100+ examples per class)
2. Retrain model: `python train_model.py --verbose`
3. Check training metrics in `model/model_audit.json`

### Duplicate Applications

**Issue:** Same job application appears multiple times
**Solution:**

- Already handled! `Application.thread_id` prevents duplicates via unique constraint
- Verify: `python manage.py shell` → `from tracker.models import Application; Application.objects.values('thread_id').annotate(count=Count('id')).filter(count__gt=1)`

### Memory Issues with Large Ingest

**Error:** `MemoryError` during 1000+ message ingestion
**Solution:**

```bash
# Ingest in batches
python manage.py ingest_gmail --after 2025/01/01 --before 2025/01/31
python manage.py ingest_gmail --after 2025/02/01 --before 2025/02/28
```

### Import Errors

**Error:** `ModuleNotFoundError: No module named 'spacy'`
**Solution:**

```bash
# Verify virtual environment is activated
which python  # Linux/macOS
where python  # Windows

# Reinstall dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

## Development Mode

### Run Tests

```bash
pytest
pytest --cov=tracker --cov-report=html  # With coverage
```

### Enable Debug Logging

```python
# In parser.py, line ~10
DEBUG = True
```

### Reset Database (WARNING: Deletes all data)

```bash
python scripts/reset_tracker.py
```

### Export/Import Data

```bash
# Export companies
python manage.py export_companies > companies_backup.json

# Import companies
python manage.py import_companies companies_backup.json
```

## Uninstallation

```bash
# Deactivate virtual environment
deactivate

# Remove project directory
cd ..
rm -rf GmailJobTracker  # Linux/macOS
Remove-Item -Recurse -Force GmailJobTracker  # Windows PowerShell
```

**Revoke Gmail API access:**

1. Visit: <https://myaccount.google.com/permissions>
2. Find "GmailJobTracker"
3. Click "Remove Access"

## Getting Help

- **Issues:** <https://github.com/><your-username>/GmailJobTracker/issues
- **Documentation:** See `markdown/` directory for detailed guides
- **Contributing:** See `CONTRIBUTING.md` for contribution guidelines

## Next Steps

1. ✅ Dashboard running at <http://127.0.0.1:8000/>
2. 📧 Label 50-100 messages to train classifier
3. 🏢 Review company resolution in admin panel
4. 📊 Check metrics dashboard for weekly stats
5. 📅 Set up automatic daily sync (optional)

---

**Privacy Notice:** All data stays local. No external servers. OAuth tokens stored in `json/token.json` (gitignored).
