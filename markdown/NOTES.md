# Version Release Workflow (Authoritative Local Copy)

This project uses the local `main` branch as the **source of truth**.  
When creating a new version, follow this process to update the repository and push to the remote.

---

## 1. Commit All Local Changes

```bash
git status
if there are changes:
git add .
git commit -m "feat: <short description of changes>"

## 2. Update CHANGELOG.md
- Move items from [Unreleased] into a new version section with today’s date.
- Save and commit:
git add CHANGELOG.md
git commit -m "docs: update changelog for vX.Y.Z"

## 3. Create Annotated Tag
git tag -a vX.Y.Z -m "Release vX.Y.Z: <short summary from changelog>"

## 4. Push Local Main to Remote (Overwrite Remote)
git push origin main --force

## 5. Push the New Tag
git push origin vX.Y.Z

## Example for v2.2.2
git add .
git commit -m "feat: implement job title extraction improvements"
git add CHANGELOG.md
git commit -m "docs: update changelog for v2.2.2"
git tag -a v2.2.2 -m "Release v2.2.2: job title extraction improvements"
git push origin main --force
git push origin v2.2.2


# Kill all python prodcessess on PowerShell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Code Analysis
✅ Summary
I've created a comprehensive set of code quality management scripts to address your concerns about dead code, redundancy, and oversized files in your GmailJobTracker project.

📦 Created Files
Core Scripts (4):

analyze_code_quality.py - Detects dead code, duplicates, complexity, and unused imports
suggest_refactoring.py - Analyzes large files and suggests how to split them
clean_imports.py - Safely removes unused imports with confirmation
run_all_checks.py - Convenient wrapper to run all checks at once
Documentation (4):
5. CODE_QUALITY_SCRIPTS.md - Comprehensive guide with usage, workflows, and safety info
6. QUICK_REFERENCE.md - Quick command reference card
7. IMPLEMENTATION_SUMMARY.md - Detailed overview and getting started guide
8. README.py - Interactive quick start guide

🎯 How These Address Your Concerns
1. Dead Code Detection

Finds unused functions and classes
Excludes Django-specific patterns (admin, views with decorators)
Generates JSON report for tracking
2. Redundant Code Detection

Identifies duplicate code blocks (5+ lines)
Shows where similar code appears multiple times
Suggests opportunities for creating shared utilities
3. Oversized Files (views.py = 3951 lines)

Categorizes your 87 functions by purpose
Suggests specific module structure:
views_company.py - Company management
views_messages.py - Message/label handling
views_domain.py - Domain configuration
views_ingestion.py - Gmail ingestion
views_dashboard.py - Dashboard/metrics
views_api.py - API endpoints
utils/validators.py - Validation helpers
utils/parsers.py - Parsing helpers
🚀 Quick Start
Run all checks at once:

This will:

Analyze code quality → code_quality_report_TIMESTAMP.json
Generate refactoring plan → refactor_plan.txt
Check for unused imports (safe, no changes)
Analyze views.py specifically
🛡️ Safety Features
All scripts are safe by default:

✅ Read-only analysis (no automatic modifications)
✅ Dry-run defaults for cleanup operations
✅ Confirmation prompts before any changes
✅ Preserves essential Django/Python imports
✅ Version control friendly
📅 Recommended Usage
Weekly maintenance:

Before refactoring:

Import cleanup:

📚 Documentation
Full guide: CODE_QUALITY_SCRIPTS.md
Quick reference: QUICK_REFERENCE.md
Implementation details: IMPLEMENTATION_SUMMARY.md
All scripts have built-in --help for detailed options!

