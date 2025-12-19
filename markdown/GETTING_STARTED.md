# 🚀 Getting Started with GmailJobTracker

**Complete setup guide for new users (15-20 minutes)**

This guide will walk you through everything needed to get GmailJobTracker running on your machine.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Gmail API Setup](#gmail-api-setup)
3. [Application Installation](#application-installation)
4. [First-Time Configuration](#first-time-configuration)
5. [Initial Data Ingestion](#initial-data-ingestion)
6. [Using the Dashboard](#using-the-dashboard)
7. [Training the ML Model](#training-the-ml-model)
8. [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

### Required Software

- **Python 3.10 or higher** (tested on 3.10-3.13)
  - Check: `python --version` or `python3 --version`
  - Download: <https://www.python.org/downloads/>

- **Git** (for cloning the repository)
  - Check: `git --version`
  - Download: <https://git-scm.com/downloads>

- **Gmail Account** with job hunting emails

### Optional

- **Docker Desktop** (if using Docker deployment)
- **Text editor** (VS Code, Sublime Text, etc.)

---

## 2. Gmail API Setup

### 2.1 Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "GmailJobTracker")
3. Enable Gmail API:
   - Navigate to "APIs & Services" → "Library"
   - Search for "Gmail API"
   - Click "Enable"

### 2.2 Create OAuth 2.0 Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure the OAuth consent screen:
   - User Type: **External**
   - App name: **GmailJobTracker**
   - User support email: **your email**
   - Developer contact: **your email**
   - Scopes: Add `https://www.googleapis.com/auth/gmail.readonly`
   - Test users: Add **your Gmail address**
4. Create OAuth client ID:
   - Application type: **Desktop app**
   - Name: **GmailJobTracker Desktop**
5. Download the JSON file (will be named something like `client_secret_....json`)

### 2.3 Save Credentials

Rename the downloaded file to `credentials.json` and place it in the `json/` directory of this project:

```bash
mv ~/Downloads/client_secret_*.json json/credentials.json
```

**⚠️ Important:** Never commit `credentials.json` to version control (it's in `.gitignore`)

---

## 3. Application Installation

### 3.1 Clone Repository

```bash
git clone https://github.com/cyberthreatgurl/GmailJobTracker.git
cd GmailJobTracker
```

### 3.2 Create Virtual Environment

**Windows:**

```powershell
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` in your terminal prompt.

### 3.3 Install Dependencies

```bash
# Install Python packages
pip install -r requirements.txt

# Download spaCy language model (for company name extraction)
python -m spacy download en_core_web_sm
```

**💡 Tip:** For development (includes testing/linting tools):

```bash
pip install -r requirements-dev.txt
```

---

## 4. First-Time Configuration

### 4.1 Create Environment File

Copy the example environment file:

```bash
# Windows
copy .env.example .env

# macOS/Linux  
cp .env.example .env
```

### 4.2 Edit .env File

Open `.env` in a text editor and configure:

```dotenv
# Required: Gmail root label (e.g., #job-hunt)
GMAIL_ROOT_FILTER_LABEL=#job-hunt

# Optional but recommended: Your email to exclude your replies
USER_EMAIL_ADDRESS=your-email@gmail.com

# Optional: Custom start date for reports (default: 7 days ago)
REPORTING_DEFAULT_START_DATE=2025-01-01

# Debug mode (True for development)
DEBUG=True

# Allowed hosts (localhost for local development)
ALLOWED_HOSTS=localhost,127.0.0.1
```

**📝 Notes:**

- `GMAIL_ROOT_FILTER_LABEL`: If you organize job hunting emails with Gmail labels, set this to your parent label name
- `USER_EMAIL_ADDRESS`: Excludes your sent emails from statistics (optional but recommended)
- `DJANGO_SECRET_KEY`: Auto-generated if not provided (fine for local use)

### 4.3 Initialize Database

```bash
# Create database tables
python manage.py migrate

# Create admin user (optional but recommended)
python manage.py createsuperuser
# Follow prompts to set username/email/password
```

### 4.4 Gmail Authentication

**⚠️ Critical Step:** Authenticate with Gmail (opens browser for OAuth)

```bash
python gmail_auth.py
```

This will:

1. Open your browser automatically
2. Ask you to sign in to Google
3. Show permissions (read-only Gmail access)
4. Save authentication token to `model/token.pickle`

**🔒 Security Notes:**

- `token.pickle` contains your OAuth tokens - keep it secret!
- It's automatically ignored by git
- Tokens expire after 7 days of inactivity (re-run `gmail_auth.py` if needed)
- Revoke access anytime: <https://myaccount.google.com/permissions>

---

## 5. Initial Data Ingestion

### 5.1 First Ingestion (Last 7 Days)

```bash
python manage.py ingest_gmail --days-back 7
```

**What This Does:**

- Fetches last 7 days of emails from Gmail
- Classifies each message (ML + regex patterns)
- Extracts company names
- Stores in local SQLite database

**Expected Output:**

```
Authenticated as: your-email@gmail.com
Fetching messages from last 7 days...
Found 150 messages to process
Processing: 100% |████████████████| 150/150
✓ Inserted: 145 messages
✓ Skipped (duplicates): 5 messages
✓ Ignored (noise): 0 messages
```

**⏱️ Time:** ~1-2 minutes for 100 messages

### 5.2 Full Historical Ingestion (Optional)

If you want to import all job hunting emails:

```bash
# Import last 90 days (recommended)
python manage.py ingest_gmail --days-back 90

# Import last 365 days (takes longer)
python manage.py ingest_gmail --days-back 365
```

**⚠️ Note:** Gmail API rate limits: 250 quota units/user/second. The app handles this automatically with retries.

---

## 6. Using the Dashboard

### 6.1 Start the Server

```bash
python manage.py runserver
```

**Output:**

```
Django version 4.2, using settings 'dashboard.settings'
Starting development server at http://127.0.0.1:8000/
Quit the server with CTRL-BREAK.
```

### 6.2 Access the Dashboard

Open your browser and navigate to: <http://127.0.0.1:8000/>

**Dashboard Features:**

- **📊 Summary Stats**: Total companies, applications, rejections, interviews
- **📈 Activity Chart**: Timeline of applications/rejections/interviews
- **🏢 Company Lists**: Filter by status (applied, rejected, interviewed, ghosted)
- **🔍 Search**: Find specific companies or messages
- **📅 Date Filter**: View activity for custom date ranges

### 6.3 Key Pages

| Page | URL | Purpose |
|------|-----|---------|
| **Dashboard** | `/` | Main overview with stats and charts |
| **Label Messages** | `/label_messages/` | Review and correct ML classifications |
| **Label Companies** | `/label_companies/` | Review and merge company names |
| **Company Threads** | `/company_threads/` | View conversation threads per company |
| **Metrics** | `/metrics/` | ML model accuracy and training stats |
| **Admin Panel** | `/admin/` | Advanced database management |

---

## 7. Training the ML Model

### 7.1 Initial Training

The ML model ships with pre-trained weights, but you should retrain with your own data for best accuracy:

1. **Label 20-50 messages:**
   - Go to <http://127.0.0.1:8000/label_messages/>
   - Review messages with low confidence (<0.70)
   - Correct any misclassifications
   - Click "Save Labels"

2. **Retrain model:**
   - Go to Quick Actions dropdown → "Retrain Model"
   - Wait 30-60 seconds
   - Check new accuracy on <http://127.0.0.1:8000/metrics/>

### 7.2 Model Performance

**Expected Accuracy After Initial Training:**

- **Overall:** 80-85%
- **Applications:** 90-95% (high precision)
- **Rejections:** 75-80% (harder to classify)
- **Interviews:** 85-90%
- **Noise:** 90-95%

**Improving Accuracy:**

- Label more examples of misclassified types
- Add custom patterns to `json/patterns.json`
- Review "Other" category and reclassify
- Model auto-retrains every 20 labels

---

## 8. Troubleshooting

### Common Issues

#### 🔴 "No module named 'tracker'"

**Problem:** Django can't find the tracker module

**Solution:**

```bash
# Make sure you're in the project root
pwd  # Should show .../GmailJobTracker

# Verify manage.py exists
ls manage.py

# Run from project root
python manage.py runserver
```

#### 🔴 "Token has been expired or revoked"

**Problem:** Gmail authentication token expired

**Solution:**

```bash
# Delete old token
rm model/token.pickle

# Re-authenticate
python gmail_auth.py
```

#### 🔴 "Rate limit exceeded"

**Problem:** Hit Gmail API quota (250 units/second)

**Solution:**

- Wait 60 seconds and try again
- Ingest in smaller batches: `--days-back 7` instead of `--days-back 90`
- The app automatically retries with exponential backoff

#### 🔴 "No messages found"

**Problem:** Ingestion returns 0 messages

**Possible Causes:**

1. **Wrong label:** Check `GMAIL_ROOT_FILTER_LABEL` in `.env`
2. **No emails in timeframe:** Try longer `--days-back`
3. **Authentication issue:** Re-run `gmail_auth.py`

**Debug:**

```bash
# Test Gmail connection
python -c "from gmail_api import authenticate_gmail; client = authenticate_gmail(); print('✓ Connected')"
```

#### 🔴 "Database is locked"

**Problem:** SQLite database locked (rare on single-user systems)

**Solution:**

```bash
# Stop server
# Delete database and re-create
rm db/job_tracker.db
python manage.py migrate
python manage.py ingest_gmail --days-back 7
```

### Getting Help

- **Documentation:** See [README.md](README.md) for architecture details
- **Installation Guide:** See [INSTALL.md](INSTALL.md) for advanced setup
- **Docker Deployment:** See [DOCKER_README.md](DOCKER_README.md)
- **CI/CD Setup:** See [markdown/CI_CD_DOCUMENTATION.md](markdown/CI_CD_DOCUMENTATION.md)
- **Issues:** Open an issue on GitHub

---

## 🎯 Next Steps

Once you have the dashboard running:

1. **Review Classifications:**
   - Check low-confidence messages
   - Correct any misclassifications
   - Retrain model

2. **Organize Companies:**
   - Merge duplicate company names (e.g., "Google" vs "Google LLC")
   - Mark headhunters (auto-excluded from stats)
   - Add career page URLs

3. **Customize Patterns:**
   - Edit `json/patterns.json` for custom regex patterns
   - Add company domain mappings to `json/companies.json`
   - Configure email filters in Gmail

4. **Set Up Automation:**
   - Schedule daily ingestion with cron/Task Scheduler
   - Enable auto-review for high-confidence messages
   - Export weekly stats

5. **Explore Advanced Features:**
   - Company threads view (see email conversations)
   - ML entity extraction (extract job titles, locations)
   - Audit logs (track all database changes)

---

## 📚 Additional Resources

- **[README.md](README.md)** - Feature overview and architecture
- **[INSTALL.md](INSTALL.md)** - Detailed installation guide
- **[DOCKER_README.md](DOCKER_README.md)** - Docker deployment
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contribution guidelines
- **[LICENSE](LICENSE)** - MIT License
- **[CHANGELOG.md](markdown/CHANGELOG.md)** - Version history

---

## ⚠️ Important Reminders

✅ **Keep credentials secure:**

- Never commit `credentials.json` or `token.pickle`
- Don't share `.env` file
- Revoke OAuth access if compromised

✅ **Local-only data:**

- All data stays on your machine
- No cloud sync or external APIs
- Backup `db/job_tracker.db` regularly

✅ **Privacy-first:**

- Read-only Gmail access
- No telemetry or tracking
- Review OAuth permissions anytime

---

**Happy job hunting! 🎉**

Need help? Open an issue on GitHub or check the documentation.
