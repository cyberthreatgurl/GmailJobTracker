# Test Harnesses and Diagnostics

This document lists the lightweight test scripts and how to run them. Each script is safe to run locally and prints an easy-to-skim result.

## Prerequisites

- Windows PowerShell (or any shell with your virtualenv activated)
- Repository root as current directory
- Python venv with project dependencies installed

Most scripts self-configure Django by setting `DJANGO_SETTINGS_MODULE=dashboard.settings` and calling `django.setup()`. No extra environment is required unless noted.

## Subdomain-aware domain mapping

File: `test_subdomain_mapping.py`

Purpose: Verifies that company resolution maps subdomains to the root domain (unless the root is an ATS), e.g., `uwe.nsa.gov → National Security Agency`.

Run:

```powershell
python test_subdomain_mapping.py
```

Expected (abridged):

```text
[DEBUG] Domain mapping (subdomain aware) used: uwe.nsa.gov -> National Security Agency
{'company': 'National Security Agency', ..., 'label': 'job_application', 'ignore': False}
```

## Rules-first label for NSA processing update

File: `test_nsa_processing_update.py`

Purpose: Confirms the rule-based rejection for “NSA Employment Processing Update” supersedes noisy ML predictions.

Run:

```powershell
python test_nsa_processing_update.py
```

Expected:

```text
rule_label: rejected
{'label': 'rejected', 'confidence': 0.95, 'ignore': False, 'method': 'rules'}
```

## Reclassify previously ignored NSA messages

File: `scripts/reclassify_nsa_processing_update.py`

Purpose: Finds and re-ingests previously ignored Gmail messages matching “NSA Employment Processing Update”. Dry-run by default.

Run (dry-run):

```powershell
python scripts/reclassify_nsa_processing_update.py
```

Apply changes:

```powershell
python scripts/reclassify_nsa_processing_update.py --apply
```

Expected (dry-run):

```text
Found N existing Message row(s) and M IgnoredMessage row(s).
Total unique Gmail IDs to re-ingest: K
DRY-RUN: No changes made. Re-run with --apply to re-ingest.
```

## Company database validation

File: `validate_companies.py`

Purpose: Validates referential integrity and points out data quality issues (orphans, duplicates, empty companies, missing `company_source`).

Run (verbose):

```powershell
python validate_companies.py --verbose
```

Auto-fix orphans:

```powershell
python validate_companies.py --fix-orphans
```

Exit codes: `0` (healthy), `1` (issues found).

## Cleanup empty companies

File: `cleanup_empty_companies.py`

Purpose: Lists and optionally deletes companies with no messages or threads. Dry-run by default, transaction-safe when applying.

Run (dry-run):

```powershell
python cleanup_empty_companies.py
```

Apply deletion (with age guard):

```powershell
python cleanup_empty_companies.py --apply --min-age-days 7
```

## Deletion race-condition scenario

File: `test_company_deletion.py`

Purpose: Recreates the “company already deleted” warning scenario to show it’s expected UX behavior when a stale `?company=<id>` param is present after deletion.

Run:

```powershell
python test_company_deletion.py
```

Expected:

```text
✅ EXPECTED: Company.DoesNotExist exception raised
The view correctly handles this with a user-friendly warning.
```

## Notes

- Subdomain mapping intentionally skips ATS roots (icims, workday, greenhouse, lever, indeed, …). Those remain handled by ATS logic (aliases, cleaned display name).
- If you add new roots to `domain_to_company` in `json/companies.json`, subdomains will resolve automatically.
- To broaden rule coverage, add safe, specific patterns under `json/patterns.json → message_labels`.
