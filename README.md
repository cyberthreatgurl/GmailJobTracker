# JobTracker

A forensic-grade job application tracker built in Python using the Gmail API and SQLite. It parses sent and received emails, classifies interactions (outreach, response, interview, rejection), and logs them for audit clarity and metric analysis.

## Features

- Gmail API integration with OAuth
- Message classification via external pattern file
- SQLite database for persistent tracking
- CLI-ready modular architecture
- Metrics: ghosting rate, response time, interview conversion

## Setup

1. Clone the repo
2. Add your `credentials.json` from Google Developer Console
3. Run `main.py` to authenticate and sync messages

## File Structure

job-tracker/
├── main.py
├── gmail_auth.py
├── parser.py
├── db.py
├── patterns.json
├── token.pickle
├── credentials.json
├── job_tracker.db
├── README.md
├── CHANGELOG.md

## License

MIT (or your preferred license)
