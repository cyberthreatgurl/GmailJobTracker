# GmailJobTracker Dashboard

A local-only Django dashboard for tracking job applications, interviews, and message threads.  
No data leaves your machine. No external servers. Just clean, private job tracking.

## Features

- Threaded message viewer per company
- Weekly/monthly rejection/interview stats
- Upcoming interview calendar
- Clickable company listing with full message history
- Requires Gmail OAuth setup and label configuration.
## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

## Privacy Statement

This tool stores all data locally in db.sqlite3. It does not communicate with any external server.


---

## 🧠 Next Step: Scaffold Django App

Let me know when you’re ready and I’ll generate:
- `models.py` with threading logic
- `views.py` for dashboard metrics
- `urls.py` routing
- Starter templates for metrics + company threads

