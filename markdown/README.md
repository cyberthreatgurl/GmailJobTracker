# GmailJobTracker Dashboard

A local-only Django dashboard for tracking job applications, interviews, and message threads.  
No data leaves your machine. No external servers. Just clean, private job tracking.

## Features

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Check environment readiness
python check_env.py

# Visit the admin panel and label messages
# After labeling, the model will retrain automatically and show training output
To view environment diagnostics:

## Privacy Statement

This tool stores all data locally in db.sqlite3. It does not communicate with any external server.


The application logs to `logs/tracker.log` for custom ingestion/debug messages and standard Django logging outputs to console (or a file in production). Review this file to analyze ingestion steps and classification decisions.
Daily log rotation is enabled:

* Custom ingestion/debug messages: `logs/tracker-YYYY-MM-DD.log` (one file per day, created on first write).
* Django framework logs: `logs/django.log` rotated at midnight retaining recent backups (development) or `/app/logs/django.log` in Docker.

If a legacy `logs/tracker.log` file exists it will stop growing after migration; new entries go to the dated file. You can safely archive or delete the old file.

Retention (production) is controlled via the `DJANGO_LOG_BACKUPS` environment variable (default 30 days). Adjust as needed for disk space and audit requirements.

```markdown
- Environment diagnostics via `/admin/environment_status/`
- Secret scanning with `detect-secrets` baseline enforcement
- Auto-retraining of ML model after labeling

---

## 🧠 Next Step: Scaffold Django App

Let me know when you’re ready and I’ll generate:
- `models.py` with threading logic
- `views.py` for dashboard metrics
- `urls.py` routing
- Starter templates for metrics + company threads

