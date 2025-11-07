# Company Validation - Quick Reference

## What's the "Already Deleted" Error?

**TL;DR**: It's not a bug - it's expected behavior when your browser URL still references a deleted company.

### The Scenario
1. You select a company → URL becomes `/label_companies/?company=123`
2. You delete the company → Company 123 is gone
3. Browser refreshes with old URL → Tries to load company 123
4. View shows: "⚠️ Company may have already been deleted"

**Your database is fine!** This is just a UI flow quirk, not data corruption.

## New Validation Tools

### 1. validate_companies.py - Database Health Check

```bash
# Quick check
python validate_companies.py

# Detailed report
python validate_companies.py --verbose

# Auto-fix issues
python validate_companies.py --fix-orphans
```

**Checks for:**
- Orphaned records (shouldn't happen but checks for corruption)
- Duplicate company names (data quality)
- Empty companies (cleanup candidates)
- Data consistency issues

**Your database status:**
```
✅ DATABASE INTEGRITY: HEALTHY
No critical issues found.

ℹ️  56 empty companies (no messages/threads)
ℹ️  2 messages missing company_source annotation
```

### 2. cleanup_empty_companies.py - Remove Orphans

```bash
# See what would be deleted (safe)
python cleanup_empty_companies.py

# Actually delete them
python cleanup_empty_companies.py --apply
```

**Safety features:**
- Dry-run by default (no changes without --apply)
- Keeps recent companies (< 7 days old)
- Asks for confirmation
- Transaction-safe (all or nothing)

### 3. test_company_deletion.py - Test the Scenario

```bash
python test_company_deletion.py
```

Simulates the deletion scenario and verifies database integrity.

## Quick Maintenance Routine

```bash
# 1. Check database health
python validate_companies.py --verbose

# 2. Review what would be cleaned
python cleanup_empty_companies.py

# 3. Clean up old empty companies (if desired)
python cleanup_empty_companies.py --apply --min-age-days 7

# 4. Verify everything is still healthy
python validate_companies.py
```

## Key Takeaways

✅ **The deletion warning is normal** - happens when URL params reference deleted companies

✅ **Database is protected** - Foreign keys prevent orphaned data:
  - Messages: `on_delete=SET_NULL` (company field becomes NULL)
  - ThreadTracking: `on_delete=CASCADE` (records deleted with company)

✅ **Validation tools detect real issues** - Run weekly to catch problems early

✅ **Empty companies are informational** - Review before cleanup (might be placeholders)

## Need More Details?

See `markdown/COMPANY_VALIDATION.md` for comprehensive documentation.
