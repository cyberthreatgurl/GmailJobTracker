# Code Quality Scripts - Implementation Summary

## 📦 Created Scripts

I've created a comprehensive set of code quality management scripts for your GmailJobTracker project:

### Main Scripts

1. **`analyze_code_quality.py`** (370+ lines)
   - Detects dead code (unused functions/classes)
   - Finds duplicate code blocks
   - Analyzes file complexity and size
   - Identifies unused imports
   - Generates JSON reports for tracking over time

2. **`suggest_refactoring.py`** (280+ lines)
   - Analyzes large files (like your 4000+ line views.py)
   - Categorizes functions by purpose (Company Views, Message Views, API Views, etc.)
   - Suggests specific module structure for splitting
   - Generates comprehensive refactoring plans
   - Identifies uncategorized functions that need manual review

3. **`clean_imports.py`** (180+ lines)
   - Safely removes unused imports
   - Dry-run mode by default (no accidental changes)
   - Preserves essential Django/Python imports
   - Prompts for confirmation before any changes
   - Can target specific files or entire project

4. **`run_all_checks.py`** (150+ lines)
   - Convenient wrapper to run all checks at once
   - Timestamps reports for tracking improvements
   - Generates summary of all findings
   - Optional interactive cleanup mode

### Documentation

5. **`CODE_QUALITY_SCRIPTS.md`**
   - Comprehensive guide to all scripts
   - Usage examples for each tool
   - Recommended workflows
   - Safety guarantees and troubleshooting
   - Integration tips (git hooks, CI/CD, scheduled tasks)

6. **`QUICK_REFERENCE.md`**
   - Quick command reference card
   - Common use cases
   - Weekly maintenance checklist
   - Before/after comparison workflows

## 🎯 Addressing Your Concerns

### Dead Code Detection
```powershell
python scripts/analyze_code_quality.py
```
This will identify:
- Functions defined but never called
- Classes that aren't used
- Excludes Django-specific patterns (admin, migrations, etc.)
- Excludes decorated views (login_required, csrf_exempt)

**Note**: Some "dead code" may be false positives (e.g., views called via URL routing), so always review manually.

### Redundant Code Detection
```powershell
python scripts/analyze_code_quality.py
```
Finds duplicate code blocks of 5+ lines that appear in multiple locations. Helps identify opportunities for creating shared utility functions.

### Oversized Files (views.py = 3951 lines)
```powershell
python scripts/suggest_refactoring.py --file tracker/views.py
```
This will suggest splitting into:
- `views_company.py` - Company management views
- `views_messages.py` - Message/label views  
- `views_domain.py` - Domain configuration views
- `views_ingestion.py` - Gmail ingestion views
- `views_dashboard.py` - Dashboard/metrics views
- `views_api.py` - API endpoints
- `utils/validators.py` - Validation helpers
- `utils/parsers.py` - Parsing helpers

## 🚀 Getting Started

### First Run (Safe Analysis Only)
```powershell
# Run all checks at once
python scripts/run_all_checks.py

# This will:
# 1. Analyze code quality → code_quality_report_TIMESTAMP.json
# 2. Suggest refactoring → refactor_plan_TIMESTAMP.txt  
# 3. Check for unused imports (dry-run, no changes)
# 4. Analyze views.py specifically
```

### Review the Reports
```powershell
# View the quality report
code code_quality_report_*.json

# View refactoring suggestions
code refactor_plan.txt
```

### Optional: Clean Up Imports
```powershell
# See what would be removed (safe)
python scripts/clean_imports.py --dry-run

# Actually remove unused imports (prompts for confirmation)
python scripts/clean_imports.py
```

## 📊 Sample Output

Based on your current codebase, you'll likely see:

```
📊 Code Quality Analysis for GmailJobTracker
============================================================

⚠️ Found 15 potentially unused definitions:
  tracker/views.py:
    - old_helper_function (line 1234)
    - unused_validator (line 2345)

📏 File Complexity (Top 10 largest files):
File                                     Lines      Functions  Classes
----------------------------------------------------------------------
tracker/views.py                         3951       87         0
parser.py                                2500       45         3
...

⚠️ 2 files exceed 1000 lines (consider splitting):
  - tracker/views.py: 3951 lines, 87 functions
  - parser.py: 2500 lines, 45 functions

💡 Suggested module split for views.py:

📦 views_company.py (12 functions):
  - delete_company
  - label_companies
  - merge_companies
  ...

📦 views_messages.py (15 functions):
  - label_messages
  - label_applications
  ...
```

## 🛡️ Safety Features

All scripts are designed to be **safe by default**:

1. ✅ **No automatic modifications** - Analysis only
2. ✅ **Dry-run defaults** - Cleanup scripts default to showing changes without applying them
3. ✅ **Confirmation prompts** - Any destructive operations ask for confirmation
4. ✅ **Preserves essential imports** - Won't remove Django/core Python imports
5. ✅ **Version control friendly** - Always commit before running cleanup

## 📅 Recommended Schedule

### Weekly
```powershell
python scripts/run_all_checks.py
```
Review reports, track trends over time.

### Before Major Refactoring
```powershell
# Baseline
python scripts/analyze_code_quality.py --output before.json

# Make changes...

# Compare
python scripts/analyze_code_quality.py --output after.json
```

### After Adding New Features
```powershell
python scripts/clean_imports.py --dry-run
```
Catch unused imports early.

## 🔧 Next Steps for views.py

Since views.py is your biggest file (3951 lines), here's a suggested approach:

### 1. Get Detailed Analysis
```powershell
python scripts/suggest_refactoring.py --file tracker/views.py
```

### 2. Create Module Structure
```powershell
New-Item -ItemType Directory -Path tracker/views -Force
New-Item -ItemType File -Path tracker/views/__init__.py
```

### 3. Start with One Category
Pick one group (e.g., "Company Views") and:
- Create `tracker/views/company.py`
- Move related functions there
- Update imports
- Test thoroughly

### 4. Repeat for Other Categories
Gradually move functions to appropriate modules.

### 5. Update URL Routing
Update `tracker/urls.py` to import from new locations:
```python
from tracker.views.company import delete_company, label_companies
from tracker.views.messages import label_messages
# etc.
```

## 📈 Measuring Improvement

Track these metrics over time:

1. **Total Lines in views.py**: Currently 3951
   - Goal: Under 1000 per file
   
2. **Dead Code Count**: Run analyzer to get baseline
   - Goal: Zero unused functions
   
3. **Duplicate Code Blocks**: Check report
   - Goal: Extract to shared utilities
   
4. **Unused Imports**: Run cleanup script
   - Goal: Zero unused imports

## 🤝 Integration Options

### Git Pre-commit Hook
```bash
#!/bin/bash
python scripts/analyze_code_quality.py --output .git/quality_report.json
```

### Windows Scheduled Task
```powershell
# Run every Sunday at 9am
$action = New-ScheduledTaskAction -Execute "python" -Argument "scripts/run_all_checks.py" -WorkingDirectory "C:\Users\kaver\code\GmailJobTracker"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 9am
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "GmailJobTracker Code Quality"
```

## 💡 Tips

1. **Start with dry-run**: Always use `--dry-run` first
2. **Review manually**: Don't blindly accept all suggestions
3. **Test after changes**: Run tests and manual verification
4. **Commit frequently**: Make incremental changes
5. **Track progress**: Keep old reports to measure improvement

## 🐛 Known Limitations

- **False Positives**: May flag valid code as dead (views via URL routing)
- **Simple Analysis**: Doesn't catch all forms of code duplication
- **Import Detection**: May miss indirect usage patterns
- **AST Limitations**: Can't analyze dynamically generated code

Always review suggestions manually before making changes!

## 📚 Further Reading

- PEP 8: Python Style Guide
- Django Best Practices: Two Scoops of Django
- Refactoring: Improving the Design of Existing Code (Martin Fowler)

---

**Created**: December 1, 2025
**Scripts Location**: `scripts/` directory
**Documentation**: `scripts/CODE_QUALITY_SCRIPTS.md`
