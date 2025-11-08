# Source Lines of Code (SLOC) Report

This report provides detailed statistics about the Python source code in the GmailJobTracker repository.

## Summary

- **Total Python Files**: 82
- **Total Lines**: 12,891
- **Blank Lines**: 1,743 (13.5%)
- **Comment Lines**: 1,612 (12.5%)
- **Source Lines of Code (SLOC)**: 9,536 (74.0%)

## What is SLOC?

SLOC (Source Lines of Code) represents the number of non-blank, non-comment lines in source files. It's a common metric used to estimate project size and complexity.

In this analysis:
- **Blank lines** are lines containing only whitespace
- **Comment lines** include:
  - Lines starting with `#`
  - Docstrings (triple-quoted strings)
- **SLOC** counts all other lines containing actual Python code

## Largest Files by SLOC

The top 10 files by source lines of code:

1. `tracker/views.py` - 2,794 SLOC
2. `parser.py` - 1,139 SLOC
3. `tracker/tests/test_ingest_message.py` - 545 SLOC
4. `validate_companies.py` - 373 SLOC
5. `tracker/migrations/0001_initial.py` - 277 SLOC
6. `tracker/management/commands/compare_gmail_labels.py` - 245 SLOC
7. `train_model.py` - 219 SLOC
8. `tracker/management/commands/purge_headhunter_applications.py` - 214 SLOC
9. `ml_subject_classifier.py` - 211 SLOC
10. `tracker/models.py` - 186 SLOC

## Code Distribution

The codebase is organized across several main areas:

### Core Application (`tracker/`)
The main Django application contains the majority of the codebase, including:
- Views and templates
- Models and database migrations
- Management commands for various operations
- Forms and admin interfaces
- Test suites

### Parsers and ML (`parser.py`, `ml_*.py`)
Email parsing and machine learning components for:
- Message parsing and entity extraction
- Subject classification
- Company identification

### Database Operations (`db.py`, `db_helpers.py`)
SQLite database utilities and helper functions.

### Utilities and Scripts
Various standalone scripts for:
- Data validation
- Email processing
- Testing and debugging

## How to Update This Report

To regenerate this report with current statistics, run:

```bash
python calculate_sloc.py
```

The script will analyze all Python files in the repository and display detailed statistics.

## Methodology

The SLOC calculation uses `calculate_sloc.py`, which:

1. Recursively finds all `.py` files in the repository
2. For each file, counts:
   - Total lines
   - Blank lines (lines with only whitespace)
   - Comment lines (lines starting with `#` or docstrings)
   - Source lines (everything else)
3. Aggregates statistics across all files

The script handles:
- Single-line docstrings (`"""text"""`)
- Multi-line docstrings
- Inline comments
- Mixed content (code with trailing comments is counted as SLOC)

---

*Report generated: 2025-11-08*
*Script: calculate_sloc.py*
