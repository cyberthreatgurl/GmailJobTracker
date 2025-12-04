Audit logs
==========

Overview
--------
This project writes simple newline-delimited JSON audit logs for manual actions that modify message review state. The main file is:

- `logs/clear_reviewed_audit.log`

Each line is a JSON object with contextual fields to help trace who triggered a change and what messages were affected.

When these logs are written:
- UI re-ingest flows (`Label Messages` page) write a `ui_reingest_clear` entry when they clear message review state before re-ingesting.
- The management command `clear_reviewed` also writes an audit entry when run from the CLI.

Why these logs exist
--------------------
They provide a lightweight, human- and machine-readable record of potentially destructive actions (clearing review state and re-ingesting messages). Use them to audit who initiated work, which messages were affected, and to help debug any accidental label changes.

Fields you will commonly see
---------------------------
Common fields in the audit entries include:

- `ts` / `timestamp`: ISO8601 timestamp for the event (UI entries use `ts`, CLI uses `timestamp`).
- `user`: username (UI) or OS user (CLI) who triggered the action.
- `action`: the action name (e.g., `ui_reingest_clear`).
- `source`: where the action originated (e.g., `reingest_selected`, `reingest_company`, `clear_reviewed`).
- `msg_id`: Gmail message id (if available).
- `db_id`: local DB primary key for the `Message` row (if available).
- `thread_id`: the `ThreadTracking.thread_id` for messages affected (if available).
- `company`: company name (UI flows) and `company_id` where applicable.
- `matched`, `updated`, `apps_updated`: counts written by the CLI command summarizing matched/updated rows.
- `details`: optional list of per-message detail objects (the CLI writes this) with `msg_id`, `db_id`, `thread_id`, `company_id`.
- `pid`: process id that wrote the log line (handy when multiple processes run concurrently).
- `error`, `trace`: when an error occurred while writing the audit, a fallback entry contains `error` and `trace` fields with the exception message and stack trace.

Examples
--------
Single UI entry (one-line JSON):

{"ts": "2025-12-04T00:41:24.030000", "user": "admin", "action": "ui_reingest_clear", "source": "reingest_selected", "db_id": 123, "msg_id": "EXAMPLE_MSG_ID_1", "thread_id": "EXAMPLE_MSG_ID_1", "company_id": 45, "pid": 31024}

CLI entry (management command `clear_reviewed`):

{
  "timestamp": "2025-12-04T00:50:00Z",
  "user": "kaver",
  "msg_ids": ["EXAMPLE_MSG_ID_1"],
  "db_ids": [123],
  "matched": 1,
  "updated": 1,
  "apps_updated": 1,
  "details": [{"msg_id": "EXAMPLE_MSG_ID_1", "db_id": 123, "thread_id": "EXAMPLE_MSG_ID_1", "company_id": 45}],
  "pid": 31024
}

How to query
------------
These files are newline-delimited JSON; use `jq` or Python to filter them.

- Show lines for a specific `msg_id` (shell):

```powershell
# Windows PowerShell

Get-Content logs\clear_reviewed_audit.log | Select-String 'EXAMPLE_MSG_ID_1' | ForEach-Object { $_.Line }
# Unix
grep 'EXAMPLE_MSG_ID_1' logs/clear_reviewed_audit.log
```

- Pretty-print all entries using `jq` (requires installing `jq`):

```bash
jq -C . logs/clear_reviewed_audit.log | less -R
```

- Extract all CLI runs with `apps_updated > 0` (jq):

```bash
jq -c 'select(.apps_updated != null and .apps_updated > 0)' logs/clear_reviewed_audit.log
```

Notes and recommendations
-------------------------
- The audit file is append-only and not encrypted; for high-security environments consider shipping logs to a centralized log store (Splunk/ELK/CloudWatch) and restricting filesystem access.
- If you want richer querying, we can add a small Django `AuditEvent` model and write audit rows to the DB (or both DB + file). This makes filtering and retention policies easier.

Where this is implemented
-------------------------
- UI writes: `tracker/views.py` (re-ingest handlers)
- CLI writes: `tracker/management/commands/clear_reviewed.py`

If you'd like, I can add a DB-backed `AuditEvent` model and a management command to reindex the file-backed entries into the DB for historical analysis.


Import workflow
---------------
This repository includes a management command that parses the newline-delimited JSON audit file and can persist entries into the DB:

- Command: `python manage.py import_audit_logs`
- Location: `tracker/management/commands/import_audit_logs.py`

Key behaviors and flags:

- Dry-run by default: the command only parses and prints a summary unless `--apply` is passed.
- `--file PATH`: path to the NDJSON audit file (default: `logs/clear_reviewed_audit.log`).
- `--limit N`: process at most N lines (useful for large files or testing).
- `--skip-existing`: when applying, skip entries that appear to already exist in the DB.
- Backup: when `--apply` is used the command copies the source file to a timestamped backup (`logs/clear_reviewed_audit.log.bak.YYYYMMDDTHHMMSSZ`) before writing to the DB.
- Deduplication: the importer performs basic heuristics to avoid duplicate rows (by `pid`, or by `created_at + action + msg_id`).

Example (PowerShell):

```powershell
# Dry-run (default)
python manage.py import_audit_logs --file logs/clear_reviewed_audit.log

# Dry-run limited to first 50 lines
python manage.py import_audit_logs --file logs/clear_reviewed_audit.log --limit 50

# Apply (persist to DB) and create a backup of the file first
python manage.py import_audit_logs --file logs/clear_reviewed_audit.log --apply

# Apply but skip entries that appear to be duplicates
python manage.py import_audit_logs --file logs/clear_reviewed_audit.log --apply --skip-existing
```

Important operational notes:

- Migration: make sure the `AuditEvent` model/migration has been applied first. Run `python manage.py migrate` before using `--apply`.
- Backup & recovery: the command makes a local backup before writes. Consider copying backups to your archival store if you require long-term retention.
- Concurrency: the importer uses simple dedupe heuristics but is not hardened for concurrent writers. Avoid running multiple `--apply` imports against the same file at once.

 
Retention policy recommendations
-------------------------------
These are suggestions — adjust to your audit and compliance needs.

- File-backed logs: keep the active `logs/clear_reviewed_audit.log` on disk for 90 days by default and move older backups into an `logs/archive/` directory or an external object store (S3/Blob/CloudWatch).
- DB-backed `AuditEvent` rows: retain in DB for 3 years by default, or use a shorter window (e.g., 1 year) if you have storage concerns. Implement a periodic cleanup job to purge older rows (not included here).
- Backups of the NDJSON file: keep at least one copy of the pre-import backup until you confirm import integrity; then archive or delete according to your retention schedule.

Suggested operational steps for historical import
----------------------------------------------

1. Ensure migrations have been applied: `python manage.py migrate`.
2. Run a dry-run to preview: `python manage.py import_audit_logs --file logs/clear_reviewed_audit.log --limit 100`.
3. If the output looks good, run with `--apply` to persist rows and create a backup.
4. Move backups to `logs/archive/` or external storage and rotate according to your retention policy.

If you'd like, I can add a small management command that archives processed files after import, or a periodic cleanup task to purge old `AuditEvent` rows.
