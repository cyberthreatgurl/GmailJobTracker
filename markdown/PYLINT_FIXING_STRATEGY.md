# Pylint Error Fixing Strategy

## Overview
This document outlines a systematic approach to fixing 1000+ pylint errors identified in the GmailJobTracker codebase.

## Error Distribution (Top 30)

| Error Type | Count | Auto-Fixable | Priority |
|------------|-------|--------------|----------|
| broad-exception-caught | 30 | ❌ Manual | High |
| missing-function-docstring | 27 | ⚠️ Semi | Medium |
| wrong-import-order | 24 | ✅ Yes | High |
| line-too-long | 24 | ✅ Yes | Low |
| wrong-import-position | 20 | ✅ Yes | High |
| missing-module-docstring | 15 | ✅ Yes | Medium |
| import-error | 15 | ❌ Manual | Critical |
| too-many-nested-blocks | 14 | ❌ Refactor | Low |
| import-outside-toplevel | 13 | ⚠️ Semi | Medium |
| invalid-name | 12 | ⚠️ Semi | Low |
| unused-import | 12 | ✅ Yes | High |
| reimported | 11 | ✅ Yes | High |
| redefined-outer-name | 9 | ❌ Manual | Medium |
| missing-final-newline | 6 | ✅ Yes | High |
| ungrouped-imports | 6 | ✅ Yes | High |
| no-else-return | 6 | ✅ Yes | Low |

## 🎯 Phase 1: Quick Wins (Automated Fixes)

### Priority: HIGH - Import Issues (68 errors)
**Tools:** `isort`, `autoflake`

```powershell
# Install tools
pip install isort autoflake

# Fix import ordering across all files
isort . --profile black --line-length 100

# Remove unused imports
autoflake --remove-all-unused-imports --in-place --recursive .

# Verify fixes
python scripts/fix_pylint_errors.py --category imports
```

**Impact:** Fixes ~68 errors
- wrong-import-order (24)
- wrong-import-position (20)
- unused-import (12)
- reimported (11)
- ungrouped-imports (6)

### Priority: HIGH - Formatting Issues (54 errors)
**Tools:** `black`, automated script

```powershell
# Install black
pip install black

# Fix line length and formatting
black . --line-length 120 --skip-string-normalization

# Fix trailing whitespace and final newlines
python scripts/fix_pylint_errors.py --category formatting

# Verify fixes
pylint . --output-format=json > scripts/debug/pylint_report_after_phase1.json
```

**Impact:** Fixes ~54 errors
- line-too-long (24)
- missing-final-newline (6)
- trailing-whitespace (2)

### Priority: MEDIUM - Documentation (42 errors)
**Tools:** Automated script + manual review

```powershell
# Add module docstrings automatically
python scripts/fix_pylint_errors.py --category docstrings

# Function docstrings require manual review
# Use this template:
"""
Brief description of function.

Args:
    param1: Description
    param2: Description

Returns:
    Description of return value
"""
```

**Impact:** Fixes ~15 errors (module docstrings)
- missing-module-docstring (15)
- missing-function-docstring (27) - requires manual review

## 🔧 Phase 2: Critical Fixes (Manual Review Required)

### Priority: CRITICAL - Import Errors (15 errors)
**Action:** Investigate and fix circular imports

Most common errors:
```python
# ERROR: Unable to import 'parser'
# CAUSE: Using deprecated 'parser' module or circular import
# FIX: Rename local parser.py or use importlib
```

**Files affected:**
- `ignore_tester.py` - Line 3: deprecated 'parser' module
- `ml_subject_classifier.py` - Line 153: circular import
- `db.py` - Line 248: Django import issue
- `parser.py` - Lines 18, 26-29: circular imports

**Solutions:**
1. **Deprecated module**: Rename local `parser.py` to `email_parser.py`
2. **Circular imports**: Use lazy imports or restructure
3. **Django imports**: Ensure DJANGO_SETTINGS_MODULE is set

### Priority: HIGH - Broad Exception Catches (30 errors)
**Action:** Replace generic `Exception` with specific exceptions

```python
# BEFORE (line 57 in db.py)
try:
    conn = sqlite3.connect(DB_PATH)
except Exception as e:
    logging.error(f"Database error: {e}")

# AFTER
try:
    conn = sqlite3.connect(DB_PATH)
except (sqlite3.Error, OSError) as e:
    logging.error(f"Database error: {e}")
```

**Common patterns:**
- File operations → `OSError`, `FileNotFoundError`, `PermissionError`
- Database → `sqlite3.Error`, `DatabaseError`
- Gmail API → `HttpError`, `RefreshError`
- JSON parsing → `json.JSONDecodeError`
- Pickle loading → `pickle.UnpicklingError`

## 🏗️ Phase 3: Code Quality Improvements (Low Priority)

### Complexity Reduction (50+ errors)
**Files needing refactoring:**

1. **parser.py** (largest issue)
   - `ingest_message()`: 361 statements, 128 branches, 67 locals
   - `parse_subject()`: 104 statements, 39 branches, 37 locals
   - **Solution:** Extract helper functions, break into smaller modules

2. **ml_subject_classifier.py**
   - `predict_subject_type()`: 56 statements, 20 branches, 20 locals
   - **Solution:** Extract preprocessing, feature engineering, prediction

**Approach:**
```python
# BEFORE: 361-line monster function
def ingest_message(msg_data):
    # ... 361 lines of code

# AFTER: Decomposed into logical units
def ingest_message(msg_data):
    metadata = extract_message_metadata(msg_data)
    company = resolve_company(metadata)
    classification = classify_message(metadata)
    return save_to_database(metadata, company, classification)
```

### Naming Conventions (12 errors)
**Pattern:** Variable names like `X`, `X_subj`, `RESUME_NOISE_PATTERNS`

```python
# BEFORE
X = vectorizer.transform([text])
X_subj = subject_vectorizer.transform([subject])
RESUME_NOISE_PATTERNS = [...]

# AFTER
features = vectorizer.transform([text])
subject_features = subject_vectorizer.transform([subject])
resume_noise_patterns = [...]
```

### No-Else-Return (6 errors)
**Pattern:** Unnecessary `elif` after `return`

```python
# BEFORE
if condition:
    return value1
elif other_condition:
    return value2
else:
    return value3

# AFTER
if condition:
    return value1
if other_condition:
    return value2
return value3
```

## 📋 Execution Plan

### Week 1: Automated Fixes (80% reduction)
```powershell
# Day 1: Setup
git checkout -b fix/pylint-cleanup
pip install isort autoflake black pylint

# Day 2: Automated formatting
python scripts/fix_pylint_errors.py --category all
isort . --profile black --line-length 100
autoflake --remove-all-unused-imports --in-place --recursive .
black . --line-length 120 --skip-string-normalization

# Day 3: Verify and commit
pylint . --output-format=json > scripts/debug/pylint_after_auto.json
python scripts/fix_pylint_errors.py --report scripts/debug/pylint_after_auto.json --category summary
git add .
git commit -m "fix: automated pylint fixes (formatting, imports, docstrings)"
```

### Week 2: Critical Manual Fixes
```powershell
# Day 1: Fix import errors (15 errors)
# - Rename parser.py → email_parser.py
# - Fix circular imports
# - Configure Django settings

# Day 2-3: Fix broad exceptions (30 errors)
# - Replace Exception with specific types
# - Add proper error handling

# Day 4-5: Testing and verification
pytest
python manage.py test
```

### Week 3: Code Quality Improvements (Optional)
```powershell
# Refactor complex functions
# - parser.py: ingest_message(), parse_subject()
# - ml_subject_classifier.py: predict_subject_type()

# This phase is optional and can be done incrementally
```

## 🛡️ Prevention: CI/CD Integration

### Add Pylint to GitHub Actions
Create `.github/workflows/code-quality.yml`:

```yaml
name: Code Quality

on: [pull_request]

jobs:
  pylint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pylint
      - name: Run pylint
        run: |
          pylint . --fail-under=8.0 --output-format=text
```

### Pre-commit Hooks
Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.9.1
    hooks:
      - id: black
        args: [--line-length=120]
  
  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort
        args: [--profile=black]
  
  - repo: https://github.com/pycqa/autoflake
    rev: v2.2.1
    hooks:
      - id: autoflake
        args: [--remove-all-unused-imports, --in-place]
  
  - repo: local
    hooks:
      - id: pylint
        name: pylint
        entry: pylint
        language: system
        types: [python]
        args: [--fail-under=8.0]
```

Install with:
```powershell
pip install pre-commit
pre-commit install
```

## 📊 Expected Results

### Before Fix
- Total errors: ~1000+
- Pylint score: ~3.5/10
- Files with errors: ~50+

### After Phase 1 (Automated)
- Total errors: ~200-300
- Pylint score: ~7.0/10
- Time: 2-3 hours

### After Phase 2 (Manual Critical)
- Total errors: ~100-150
- Pylint score: ~8.5/10
- Time: 1-2 weeks

### After Phase 3 (Quality Improvements)
- Total errors: <50
- Pylint score: ~9.5/10
- Time: 2-4 weeks (incremental)

## 🔍 Monitoring Progress

### Generate Reports
```powershell
# Before starting
pylint . --output-format=json > scripts/debug/pylint_baseline.json

# After each phase
pylint . --output-format=json > scripts/debug/pylint_phase1.json
pylint . --output-format=json > scripts/debug/pylint_phase2.json

# Compare
python scripts/fix_pylint_errors.py --report scripts/debug/pylint_phase1.json --category summary
```

### Track by File
```powershell
# Show per-file error counts
python -c "import json; from collections import Counter; data = json.load(open('scripts/debug/pylint_report.json')); files = Counter(e['path'] for e in data); print('\n'.join(f'{v:4d} {k}' for k,v in sorted(files.items(), key=lambda x: -x[1])[:20]))"
```

## 🎓 Learning Resources

- **Pylint docs**: https://pylint.readthedocs.io/
- **Black formatter**: https://black.readthedocs.io/
- **Isort**: https://pycqa.github.io/isort/
- **Python style guide (PEP 8)**: https://peps.python.org/pep-0008/
- **Google Python style**: https://google.github.io/styleguide/pyguide.html

## 🚨 Important Notes

1. **Backup first**: Create git branch before starting
2. **Test after each phase**: Run full test suite
3. **Incremental commits**: Commit after each category of fixes
4. **Don't break functionality**: Formatting should not change behavior
5. **Review auto-fixes**: Not all automated suggestions are correct

## 📞 Getting Help

If you encounter issues:
1. Check `.pylintrc` configuration
2. Review error-specific documentation in pylint docs
3. Use `--help-msg=<error-code>` for detailed explanations
   ```powershell
   pylint --help-msg=broad-exception-caught
   ```
