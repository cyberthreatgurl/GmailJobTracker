# Pylint Error Fix - Quick Reference

## 📊 Current Status

**Total Errors:** 1000+  
**Current Pylint Score:** ~3.5/10  
**Files Affected:** 50+

## 🎯 Top Error Categories

| Category | Count | Fix Method |
|----------|-------|------------|
| broad-exception-caught | 30 | Manual review |
| missing-function-docstring | 27 | Semi-automated |
| wrong-import-order | 24 | **Automated (isort)** |
| line-too-long | 24 | **Automated (black)** |
| wrong-import-position | 20 | **Automated (isort)** |
| missing-module-docstring | 15 | **Automated** |
| import-error | 15 | Manual fix |
| unused-import | 12 | **Automated (autoflake)** |
| reimported | 11 | **Automated (autoflake)** |

## 🚀 Quick Start (Recommended)

### Option 1: Automated Phase 1 (Fastest - 80% reduction)

```powershell
# Windows PowerShell
.\scripts\fix_pylint.ps1 -Phase phase1

# Linux/macOS
bash scripts/fix_pylint.sh phase1
```

**What it does:**
- ✅ Formats code with Black
- ✅ Sorts imports with isort
- ✅ Removes unused imports with autoflake
- ✅ Fixes trailing whitespace
- ✅ Adds module docstrings
- ✅ Fixes missing final newlines

**Time:** ~5 minutes  
**Expected result:** ~800 errors → ~200 errors

### Option 2: Manual Step-by-Step

```powershell
# 1. Install tools
pip install isort autoflake black pylint

# 2. Fix formatting
black . --line-length 120 --skip-string-normalization

# 3. Fix imports
isort . --profile black --line-length 100
autoflake --remove-all-unused-imports --in-place --recursive .

# 4. Fix docstrings and whitespace
python scripts/fix_pylint_errors.py --category all

# 5. Check results
pylint . --output-format=json > scripts/debug/pylint_after_fixes.json
python scripts/fix_pylint_errors.py --report scripts/debug/pylint_after_fixes.json --category summary
```

## 📋 Files Created for You

1. **`.pylintrc`** - Configuration file
   - Disables low-priority checks
   - Sets reasonable complexity limits
   - Allows ML/data science variable names (X, y, etc.)

2. **`scripts/fix_pylint_errors.py`** - Automated fixer
   - Fixes formatting issues
   - Adds module docstrings
   - Reports manual fixes needed

3. **`scripts/fix_pylint.ps1`** - Windows automation script
   - One-command fix for Phase 1
   - Includes safety checks

4. **`scripts/fix_pylint.sh`** - Linux/macOS automation script
   - Same as PowerShell version

5. **`markdown/PYLINT_FIXING_STRATEGY.md`** - Complete guide
   - Detailed 3-phase approach
   - Examples for each error type
   - CI/CD integration instructions

## 🔍 Preview Changes (Dry Run)

Before making any changes:

```powershell
# Windows
.\scripts\fix_pylint.ps1 -Phase phase1 -DryRun

# Linux/macOS
bash scripts/fix_pylint.sh phase1 --dry-run
```

## ⚠️ Critical Issues Requiring Manual Fix

### 1. Import Errors (15 errors) - **CRITICAL**
**Problem:** Circular imports and deprecated module usage

**Files affected:**
- `ignore_tester.py` (line 3) - Using deprecated 'parser' module
- `ml_subject_classifier.py` (line 153) - Circular import
- `db.py` (line 248) - Django import issues

**Solution:**
```python
# Option 1: Rename parser.py to email_parser.py
# Option 2: Use lazy imports
# Option 3: Restructure to remove circular dependencies
```

### 2. Broad Exception Catches (30 errors)
**Problem:** Catching generic `Exception` instead of specific types

**Example fix:**
```python
# BEFORE
try:
   conn = psycopg.connect(dsn)
except Exception as e:  # Too broad!
    logging.error(f"Error: {e}")

# AFTER
try:
   conn = psycopg.connect(dsn)
except (psycopg.Error, OSError) as e:
    logging.error(f"Database error: {e}")
```

## 📈 Expected Progress

### After Automated Fixes (Phase 1)
- **Time:** 5-10 minutes
- **Errors:** 1000+ → ~200
- **Score:** 3.5/10 → 7.0/10
- **Effort:** Minimal (one command)

### After Manual Fixes (Phase 2)
- **Time:** 1-2 weeks (incremental)
- **Errors:** ~200 → ~100
- **Score:** 7.0/10 → 8.5/10
- **Effort:** Moderate (code review needed)

### After Refactoring (Phase 3 - Optional)
- **Time:** 2-4 weeks
- **Errors:** ~100 → <50
- **Score:** 8.5/10 → 9.5/10
- **Effort:** High (architectural changes)

## 🛡️ Safety Checklist

Before running automated fixes:

- [ ] Create git branch: `git checkout -b fix/pylint-cleanup`
- [ ] Ensure tests pass: `pytest`
- [ ] Ensure Django works: `python manage.py check`
- [ ] Have backup: `git status` (all changes committed)

After running automated fixes:

- [ ] Review changes: `git diff`
- [ ] Run tests: `pytest`
- [ ] Run Django tests: `python manage.py test`
- [ ] Test ingestion: `python manage.py ingest_gmail --limit-msg <id>`
- [ ] Commit: `git commit -m "fix: automated pylint fixes"`

## 🎓 Tools Used

| Tool | Purpose | Documentation |
|------|---------|---------------|
| **black** | Code formatting | https://black.readthedocs.io/ |
| **isort** | Import sorting | https://pycqa.github.io/isort/ |
| **autoflake** | Remove unused imports | https://github.com/PyCQA/autoflake |
| **pylint** | Linting/analysis | https://pylint.readthedocs.io/ |

## 💡 Pro Tips

1. **Start with automated fixes** - Get 80% reduction in 5 minutes
2. **Review diffs carefully** - Automated tools can make mistakes
3. **Fix incrementally** - Commit after each category
4. **Test frequently** - Don't break functionality
5. **Use .pylintrc** - Already configured with sensible defaults

## 🚨 Common Pitfalls to Avoid

1. ❌ **Don't** fix everything at once
   - ✅ **Do** fix by category (imports, formatting, etc.)

2. ❌ **Don't** trust all automated fixes blindly
   - ✅ **Do** review changes with `git diff`

3. ❌ **Don't** skip testing
   - ✅ **Do** run full test suite after each phase

4. ❌ **Don't** commit without review
   - ✅ **Do** check that functionality unchanged

## 📞 Need Help?

### Check error details
```powershell
pylint --help-msg=<error-code>
# Example: pylint --help-msg=broad-exception-caught
```

### View errors by file
```powershell
python -c "import json; from collections import Counter; data = json.load(open('scripts/debug/pylint_report.json')); files = Counter(e['path'] for e in data); print('\n'.join(f'{v:4d} {k}' for k,v in sorted(files.items(), key=lambda x: -x[1])[:20]))"
```

### Compare before/after
```powershell
python scripts/fix_pylint_errors.py --report scripts/debug/pylint_baseline.json --category summary
python scripts/fix_pylint_errors.py --report scripts/debug/pylint_after_phase1.json --category summary
```

## 📚 Additional Resources

- **Full Strategy:** `markdown/PYLINT_FIXING_STRATEGY.md`
- **Pylint Config:** `.pylintrc`
- **Fixer Script:** `scripts/fix_pylint_errors.py`
- **Automation:** `scripts/fix_pylint.ps1` (Windows) or `scripts/fix_pylint.sh` (Linux/macOS)

## ⏭️ Recommended Next Step

**Run automated Phase 1 fixes now:**

```powershell
# Preview what will be fixed
.\scripts\fix_pylint.ps1 -Phase phase1 -DryRun

# If looks good, apply fixes
.\scripts\fix_pylint.ps1 -Phase phase1
```

This will reduce errors by ~80% in just a few minutes! 🎉
