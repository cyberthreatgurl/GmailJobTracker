# Code Quality Scripts for GmailJobTracker

This directory contains scripts to help maintain code quality and manage technical debt.

## Available Scripts

### 1. `analyze_code_quality.py`
Comprehensive code quality analyzer that detects:
- **Dead Code**: Unused functions and classes
- **Duplicate Code**: Similar code blocks across files
- **File Complexity**: Oversized files and function counts
- **Unused Imports**: Imports that aren't being used

**Usage:**
```powershell
# Run full analysis
python scripts/analyze_code_quality.py

# Save to custom output file
python scripts/analyze_code_quality.py --output my_report.json

# Verbose mode
python scripts/analyze_code_quality.py --verbose
```

**Output:**
- Console report with key findings
- JSON file (`code_quality_report.json`) with detailed data

**Example Output:**
```
⚠️ Found 15 potentially unused definitions:
  tracker/views.py:
    - old_helper_function (line 1234)
    - unused_validator (line 2345)

📏 File Complexity (Top 10 largest files):
File                                     Lines      Functions  Classes
----------------------------------------------------------------------
tracker/views.py                         4332       87         0
parser.py                                2500       45         3
```

---

### 2. `suggest_refactoring.py`
Analyzes large files and suggests how to split them into logical modules.

**Usage:**
```powershell
# Analyze views.py (default)
python scripts/suggest_refactoring.py

# Analyze specific file
python scripts/suggest_refactoring.py --file tracker/views.py

# Generate full refactoring plan for all large files
python scripts/suggest_refactoring.py --plan

# Custom size threshold (default: 500 lines)
python scripts/suggest_refactoring.py --threshold 1000
```

**Output:**
- Categorizes functions by purpose (API views, domain views, helpers, etc.)
- Suggests module structure for splitting
- Identifies uncategorized functions
- Provides step-by-step refactoring instructions

**Example Output:**
```
📁 Analyzing: views.py
==============================================================
Total lines: 4332
Total functions: 87

⚠️ File exceeds 500 lines

💡 Suggested module split:

📦 Suggested View Modules:

  views_company.py (12 functions):
    - delete_company
    - label_companies
    - merge_companies
    ...

  views_messages.py (15 functions):
    - label_messages
    - label_applications
    ...

📦 Suggested Utility Modules:

  utils/validators.py (8 functions):
    - validate_regex_pattern
    - sanitize_string
    - validate_domain
    ...
```

---

### 3. `clean_imports.py`
Safely removes unused imports from Python files.

**Usage:**
```powershell
# Dry run (shows what would be removed, no changes)
python scripts/clean_imports.py --dry-run

# Actually remove unused imports (prompts for confirmation)
python scripts/clean_imports.py

# Clean specific file only
python scripts/clean_imports.py --file tracker/views.py --dry-run

# Verbose mode (show analysis details)
python scripts/clean_imports.py --dry-run --verbose
```

**Safety Features:**
- Dry-run mode by default
- Preserves essential Django/Python imports
- Prompts for confirmation before removing
- Shows exactly what will be removed

**Example Output:**
```
⚠️ views.py: Found 5 potentially unused imports:
  Line 45: from collections import OrderedDict
  Line 67: import logging
  Line 89: from typing import Optional

Remove these 5 imports? [y/N]:
```

---

## Recommended Workflow

### Weekly Code Quality Check
```powershell
# 1. Run analysis to identify issues
python scripts/analyze_code_quality.py

# 2. Check for unused imports (dry-run first)
python scripts/clean_imports.py --dry-run

# 3. Review refactoring suggestions
python scripts/suggest_refactoring.py --plan
```

### Before Major Refactoring
```powershell
# 1. Generate comprehensive refactoring plan
python scripts/suggest_refactoring.py --plan

# 2. Review the generated refactor_plan.txt file

# 3. Clean up imports first
python scripts/clean_imports.py

# 4. Split large files based on suggestions
# (Manual step - move functions to new modules)

# 5. Re-run analysis to verify improvements
python scripts/analyze_code_quality.py
```

### Addressing views.py (4000+ lines)

For your specific case with `views.py` being over 4000 lines:

```powershell
# 1. Get detailed breakdown
python scripts/suggest_refactoring.py --file tracker/views.py

# 2. Review suggested splits:
#    - views_company.py (company management views)
#    - views_messages.py (message/label views)
#    - views_domain.py (domain configuration views)
#    - views_ingestion.py (Gmail ingestion views)
#    - views_dashboard.py (dashboard/metrics views)
#    - views_api.py (API endpoints)
#    - utils/validators.py (validation helpers)
#    - utils/parsers.py (parsing helpers)

# 3. Create new module structure:
New-Item -ItemType Directory -Path tracker/views -Force
New-Item -ItemType Directory -Path tracker/utils -Force

# 4. Move functions to new modules (manual refactoring)

# 5. Update imports in main views.py

# 6. Verify everything still works
python manage.py runserver
```

---

## Integration Tips

### Add to Git Pre-commit Hook
Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
python scripts/analyze_code_quality.py --output .git/quality_report.json
```

### Scheduled Quality Checks
Add to Windows Task Scheduler or create a PowerShell script:
```powershell
# weekly_quality_check.ps1
cd C:\Users\kaver\code\GmailJobTracker
.\.venv\Scripts\Activate.ps1
python scripts/analyze_code_quality.py
python scripts/clean_imports.py --dry-run > logs/import_cleanup.log
```

### CI/CD Integration
Add to GitHub Actions or CI pipeline:
```yaml
- name: Code Quality Check
  run: |
    python scripts/analyze_code_quality.py
    # Fail build if dead code count exceeds threshold
```

---

## What Each Script Does NOT Do

### analyze_code_quality.py
- ❌ Does NOT modify any files
- ❌ Does NOT remove dead code automatically
- ✅ Only analyzes and reports

### suggest_refactoring.py
- ❌ Does NOT move or modify files
- ❌ Does NOT generate new module files
- ✅ Only suggests structure

### clean_imports.py
- ❌ Does NOT remove imports in dry-run mode (default)
- ❌ Does NOT remove essential Django imports
- ✅ Always asks for confirmation before changes

---

## Safety Guarantees

All scripts are designed with safety in mind:

1. **No Automatic Modifications**: Scripts analyze and suggest, they don't automatically refactor
2. **Dry-Run Defaults**: Destructive operations default to dry-run mode
3. **Confirmation Prompts**: Changes require explicit user confirmation
4. **Backup Recommended**: Always commit to git before running cleanup scripts
5. **False Positives Expected**: Dead code detection may flag valid code (e.g., views called via URL routing)

---

## Troubleshooting

**"Script finds false positive dead code"**
- Views registered in `urls.py` may appear unused
- Admin-registered models/forms may appear unused
- Signal handlers may appear unused
- ➡️ Review suggestions manually before removing

**"Import cleanup breaks the code"**
- Some imports are used indirectly (template tags, middleware)
- Always run in dry-run mode first
- Test thoroughly after cleanup
- ➡️ Use version control, commit before cleanup

**"Refactoring suggestions seem wrong"**
- AST analysis has limitations
- Function categorization is heuristic-based
- ➡️ Use suggestions as guidance, not absolute truth

---

## Future Enhancements

Possible additions to these scripts:
- [ ] Automated test coverage integration
- [ ] Cyclomatic complexity analysis
- [ ] Dependency graph visualization
- [ ] Automated module splitting (with safety checks)
- [ ] Integration with pylint/flake8/black
- [ ] Performance profiling integration

---

## Questions?

If you encounter issues or have suggestions:
1. Review the script source code (well-commented)
2. Run with `--verbose` flag for more details
3. Check generated JSON reports for raw data
