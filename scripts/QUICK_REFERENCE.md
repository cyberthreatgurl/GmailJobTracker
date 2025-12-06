# Code Quality Quick Reference

## Run All Checks at Once
```powershell
python scripts/run_all_checks.py
```

## Individual Scripts

### 1. Analyze Everything
```powershell
python scripts/analyze_code_quality.py
```
Output: `code_quality_report.json`

### 2. Get Refactoring Suggestions
```powershell
# For views.py specifically
python scripts/suggest_refactoring.py

# For all large files
python scripts/suggest_refactoring.py --plan
```
Output: Console + `refactor_plan.txt` (if --plan)

### 3. Clean Unused Imports
```powershell
# Safe: just show what would be removed
python scripts/clean_imports.py --dry-run

# Actually remove (asks for confirmation)
python scripts/clean_imports.py
```

## Quick Commands

### Check views.py size
```powershell
(Get-Content tracker/views.py).Count
```

### Find largest Python files
```powershell
Get-ChildItem -Recurse -Filter *.py | 
    Where-Object { $_.FullName -notmatch '\.venv|__pycache__' } |
    Select-Object FullName, @{N='Lines';E={(Get-Content $_.FullName).Count}} |
    Sort-Object Lines -Descending |
    Select-Object -First 10
```

### Count functions in a file
```powershell
(Select-String -Path tracker/views.py -Pattern "^def ").Count
```

## Weekly Maintenance

```powershell
# 1. Run full analysis
python scripts/run_all_checks.py

# 2. Review reports
code code_quality_report*.json
code refactor_plan.txt

# 3. Clean imports (optional)
python scripts/clean_imports.py --dry-run
```

## Before Committing Major Changes

```powershell
# Baseline before changes
python scripts/analyze_code_quality.py --output before_refactor.json

# Make your changes...

# Check after changes
python scripts/analyze_code_quality.py --output after_refactor.json

# Compare improvements
# (manually review JSON files)
```
