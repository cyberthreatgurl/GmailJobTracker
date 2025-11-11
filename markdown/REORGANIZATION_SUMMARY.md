# Repository Reorganization Summary

**Date:** November 6, 2025

## Overview
Reorganized the GmailJobTracker repository to reduce root directory clutter by moving 56+ utility scripts into organized subdirectories under `/scripts/`.

## New Structure

### Scripts Organization
```
scripts/
├── debug/          (25 files) - Debugging, checking, and investigation scripts
├── analysis/       (4 files)  - Data analysis and pattern discovery
├── verification/   (4 files)  - Post-change verification scripts
├── testing/        (14 files) - Ad-hoc test scripts
├── fixers/         (9 files)  - Data modification and correction scripts
└── README.md       (NEW)      - Documentation of scripts organization
```

## Files Moved

### To `scripts/debug/` (25 files)
- All `debug_*.py` files (debug_alias.py, debug_ats_check.py, debug_detailed.py, etc.)
- All `check_*.py` files (check_bad_company.py, check_both_endyna_msgs.py, etc.)
- `investigate_*.py` files
- `find_bad_companies.py`

### To `scripts/analysis/` (4 files)
- All `analyze_*.py` files (analyze_application_necessity.py, analyze_guidehouse_apps.py, etc.)
- `alias_candidates.py`

### To `scripts/verification/` (4 files)
- All `verify_*.py` files (verify_company_links.py, verify_ghosted_count.py, etc.)

### To `scripts/testing/` (14 files)
- All `test_*.py` files from root (test_actual_ng_email.py, test_classification_order.py, etc.)
- Note: Formal test suite remains in `/tests/` directory

### To `scripts/fixers/` (9 files)
- All `fix_*.py` files (fix_anthropic_messages.py, fix_carefirst_message.py, etc.)
- `normalize_*.py` files
- `backfill_*.py` files
- `remove_noise_companies.py`

## Files Remaining in Root
Core application files that belong in the root:
- `manage.py` - Django management script
- `parser.py` - Core message parsing logic
- `train_model.py` - ML model training
- `db.py`, `db_helpers.py` - Database utilities
- `gmail_auth.py` - Gmail OAuth authentication
- `ml_*.py` - ML model components (ml_entity_extraction.py, ml_prep.py, ml_subject_classifier.py)
- `main.py` - Main application entry point
- `get_imports.py` - Import analysis
- `label_companies.py` - Company labeling utility
- `ignore_tester.py` - Ignore pattern testing
- `changelog_*.py` - Changelog management
- `init_db.py` - Database initialization
- `tracker_logger.py` - Logging configuration

## Benefits
1. **Cleaner root directory** - Reduced from 80+ files to ~20 core application files
2. **Better organization** - Scripts grouped by purpose and function
3. **Easier navigation** - Clear categorization makes finding scripts easier
4. **Documentation** - Added README.md in scripts/ to explain organization
5. **Maintainability** - Easier to identify one-off scripts vs. core functionality

## Migration Notes
- All script functionality remains unchanged
- Import paths in scripts were not modified (they run from root context)
- Django management commands (in `tracker/management/commands/`) remain unchanged
- Consider migrating frequently-used scripts to Django management commands

## Next Steps (Optional)
1. Review scripts in each category and archive/delete obsolete ones
2. Consider consolidating similar debug scripts
3. Move frequently-used scripts to Django management commands for better integration
4. Update any documentation that references old script locations
