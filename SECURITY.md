# SECURITY.md

## Overview

This project is designed for local-only operation. No data is transmitted externally, and no third-party services are used beyond Gmail OAuth authentication.

## Threat Model

| Threat | Mitigation |
|--------|------------|
| Credential leakage | Integrated `detect-secrets` scanning with `.secrets.baseline` enforcement |
| SQL injection | All DB queries use parameterized statements |
| XSS in dashboard | Dynamic content is escaped in templates |
| Insecure model loading | ML models are loaded from local `.pkl` files only; no remote fetches |
| Git exposure | `.secrets.baseline` ensures secrets are not committed |

## Secure Coding Practices

- All external inputs (Gmail, DB, dashboard) are validated or sanitized
- No secrets are printed in logs or exposed in the admin UI
- Directory permissions and file presence are checked via `check_env.py`
- Git status and commit info are surfaced for audit traceability

## Tools

- `detect-secrets` for pre-commit and CI/CD scanning
- `check_env.py` for runtime environment validation

## Deployment Notes

- All data is stored locally in `job_tracker.db`
- OAuth credentials (`token.json`, `credentials.json`) are never uploaded or shared
- Admin-only diagnostics available at `/admin/environment_status/`