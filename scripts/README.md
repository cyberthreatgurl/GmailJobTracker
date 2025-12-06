# Scripts Directory Organization

This directory contains utility scripts organized by purpose.

## Directory Structure

### `/debug/`
Scripts for debugging and checking specific issues:
- `debug_*.py` - Debugging utilities for specific components or data issues
- `check_*.py` - Validation scripts to check data integrity and consistency
- `investigate_*.py` - Investigation scripts for analyzing specific scenarios
- `find_bad_companies.py` - Locate problematic company entries

### `/analysis/`
Scripts for analyzing data patterns and generating insights:
- `analyze_*.py` - Data analysis utilities
- `alias_candidates.py` - Analyze potential company alias candidates

### `/verification/`
Scripts for verifying fixes and changes:
- `verify_*.py` - Verification scripts to confirm expected behavior after changes

### `/testing/`
Ad-hoc test scripts (note: formal tests are in `/tests/` directory):
- `test_*.py` - Quick test scripts for specific functionality

### `/fixers/`
Scripts that modify data or fix issues:
- `fix_*.py` - Data correction scripts
- `normalize_*.py` - Data normalization utilities
- `backfill_*.py` - Scripts to backfill missing data
- `remove_noise_companies.py` - Clean up noise in company data
- `fix_import_company.py` - Fix company import issues
- `fix_patterns_simple.py` - Fix pattern configurations

### Root Scripts Directory
Operational and maintenance scripts:
- `reingest_messages.py` / `reingest-by-messageID.py` - Re-ingest Gmail messages
- `scrape_companies.py` - Scrape company information
- `import_gmail_filters.py` - Import Gmail filter configurations
- `migrate_patterns_to_regex.py` - Pattern migration utilities
- `cleanup_noise_companies.py` - Cleanup operations
- `extract_companies_from_url.py` - URL-based company extraction
- `find_companies.py` - Company discovery utilities
- `validate_companies.py` - Company data validation
- `show_unreviewed_noise.py` - Display unreviewed noise messages
- `find_high_confidence_errors.py` - Identify classification errors
- `audit_false_positive_rejections.py` - Audit rejection classification accuracy

## Usage Guidelines

1. **Debug scripts** - Use when investigating specific issues or data anomalies
2. **Analysis scripts** - Run periodically to understand data patterns
3. **Verification scripts** - Run after making changes to confirm expected outcomes
4. **Fixer scripts** - Use with caution; these modify data (consider dry-run first)
5. **Testing scripts** - Quick validation; see `/tests/` for comprehensive test suite

## Shell Scripts
- `reset_dev.sh` / `reset_tracker.py` - Development environment reset
- `sync_gmail.sh` / `runit.sh` - Operational shell scripts
- `update_copilot.ps1` / `update_copilot.sh` - Update Copilot instructions

## Data Files
- `*.json` - Configuration and data exports (archived)
- `*.txt` - Documentation and data dumps

## Notes
- Many scripts are one-off utilities created for specific issues
- Check script docstrings for usage and purpose
- Some scripts may be outdated; verify relevance before use
- Consider moving frequently-used scripts to Django management commands
