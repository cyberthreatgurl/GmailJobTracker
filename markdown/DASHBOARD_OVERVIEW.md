# DASHBOARD_OVERVIEW.md

## Overview

This dashboard provides a secure, local-only interface for tracking job applications, interviews, and message threads.

---

## Features

- Threaded message viewer per company
- Weekly/monthly rejection and interview stats
- Upcoming interview calendar
- Labeling interface with auto-retraining
- Environment diagnostics via `/admin/environment_status/`

---

## Architecture

- Django-based admin and dashboard views
- SQLite backend (`job_tracker.db`)
- Models include `Application`, `Message`, `IgnoredMessage`, `IngestionStats`
- ML artifacts stored in `/model/` as `.pkl` files

---

## Security

- No external data transmission
- All dynamic content escaped to prevent XSS
- Secret scanning enforced via `detect-secrets`
- Admin-only access to environment diagnostics

---

## Next Steps

- Implement baseline dashboard UI (Story 2)
- Add filters by status, company, and date
- Group applications by `(company, job_title, job_id)`