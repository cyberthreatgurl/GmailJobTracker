# Company Database Validation & Cleanup Tools

## Overview

This document describes the company database validation and cleanup tools for the GmailJobTracker application.

## Understanding the "Already Deleted" Warning

### What You're Experiencing

When you delete a company from the `label_companies` page, you may see a warning:
```
⚠️ Company with ID 123 not found. It may have already been deleted.
```

### Why This Happens

This is **expected behavior**, not a database error. Here's the sequence:

1. You select a company on the label_companies page (URL: `/label_companies/?company=123`)
2. You click delete and confirm
3. The company is successfully deleted
4. Your browser might refresh or you navigate back with the old URL parameter (`?company=123`)
5. The view tries to fetch company ID 123, which no longer exists
6. Django raises `Company.DoesNotExist`
7. The view catches this and shows the warning message

### Database Integrity

Your database is **NOT** corrupted. The view correctly handles this scenario with:
- Try/except block for `Company.DoesNotExist`
- User-friendly warning message
- Redirect to clean page without company parameter

## Database Foreign Key Constraints

### Current Configuration

```python
# Message model
company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL)
# When a company is deleted, Message.company is set to NULL

# ThreadTracking model
company = models.ForeignKey(Company, on_delete=models.CASCADE)
# When a company is deleted, all related ThreadTracking records are deleted
```

### What This Means

- **Messages**: When you delete a company, all messages keep their content but `company` field is set to NULL
- **ThreadTracking**: When you delete a company, all thread tracking records are **deleted entirely**
- **No orphaned references**: The database automatically maintains referential integrity

## Validation Tools

### 1. validate_companies.py

Comprehensive database integrity validator that checks for:

#### Checks Performed

✅ **Orphaned ThreadTracking Records**
- Detects ThreadTracking records with NULL company (shouldn't happen with CASCADE)
- Indicates potential database corruption

✅ **Orphaned Message References**
- Finds messages where `company_id` points to non-existent company
- Shouldn't happen with SET_NULL, but checks for corruption

✅ **Duplicate Company Names**
- Finds companies with identical names that may need merging
- Helps maintain data quality

✅ **Empty Companies**
- Lists companies with no messages or thread tracking records
- Potential cleanup candidates

✅ **Data Consistency Issues**
- Missing or empty company names
- Invalid confidence values (outside 0-1 range)
- Date inconsistencies (first_contact after last_contact)

✅ **Company Source Annotations**
- Checks if messages have company but no `company_source` annotation
- Helps track data provenance

#### Usage

```bash
# Basic validation (quiet mode)
python validate_companies.py

# Verbose output with detailed info
python validate_companies.py --verbose

# Automatically fix orphaned records
python validate_companies.py --fix-orphans
```

#### Example Output

```
================================================================================
COMPANY DATABASE VALIDATION SUMMARY
================================================================================

📊 Database Statistics:
  Total Companies:        168
  Total Messages:        1023
  Total ThreadTracking:   239

🔍 Issues Found:
  Orphaned Threads:         0
  Orphaned Messages:        0
  Duplicate Names:          0
  Empty Companies:         56
  Data Inconsistencies:     0

================================================================================
✅ DATABASE INTEGRITY: HEALTHY
No critical issues found.

ℹ️  56 company(ies) have no messages or threads.
   These may be safe to delete.
================================================================================
```

#### Exit Codes

- `0`: No critical issues found (healthy database)
- `1`: Critical issues detected (orphans or data inconsistencies)

### 2. cleanup_empty_companies.py

Removes companies that have no associated messages or thread tracking records.

#### Safety Features

- **Dry-run by default**: Won't delete anything unless you use `--apply`
- **Age protection**: By default, keeps companies created within last 7 days
- **User confirmation**: Asks for confirmation before deleting
- **Transaction safety**: Uses Django transactions (all-or-nothing deletion)

#### Usage

```bash
# Dry-run: see what would be deleted (safe, no changes)
python cleanup_empty_companies.py

# Apply changes (actually delete)
python cleanup_empty_companies.py --apply

# Delete all empty companies regardless of age
python cleanup_empty_companies.py --apply --min-age-days 0

# Keep companies newer than 30 days
python cleanup_empty_companies.py --apply --min-age-days 30
```

#### Example Output

```
================================================================================
EMPTY COMPANY CLEANUP
================================================================================
Mode: DRY RUN (no changes)
Keep Recent: True
Min Age: 7 days

Found 56 empty companies:

  1. ID   32 - Font
     Domain: infotreeglobal.com
     Status: application
     First Contact: 2025-10-15 10:30:00

  2. ID   65 - RamSoft
     Domain: ramsoft.net
     Status: application
     First Contact: 2025-10-20 14:22:00

...

⚠️  DRY RUN: Would delete 56 companies
Run with --apply to actually delete these companies
================================================================================
```

### 3. test_company_deletion.py

Test script that simulates the deletion scenario to verify expected behavior.

#### Usage

```bash
python test_company_deletion.py
```

## Best Practices

### When to Run Validation

✅ **Regular Maintenance**
- Run `validate_companies.py` weekly or monthly
- Add to CI/CD pipeline to catch issues early

✅ **After Bulk Operations**
- After merging companies
- After mass deletions
- After data imports

✅ **Before Backups**
- Validate integrity before creating database backups
- Ensure you're backing up clean data

### When to Clean Up Empty Companies

✅ **Safe to Clean**
- Companies with no messages AND no threads
- Companies older than 7+ days (not recently created)
- Companies created by mistake (typos, duplicates)

⚠️ **Be Cautious**
- Companies created as placeholders for future applications
- Companies you manually added but haven't received messages yet
- Recently created companies (they might get messages soon)

### Workflow Recommendation

```bash
# Step 1: Validate database
python validate_companies.py --verbose

# Step 2: Review empty companies (dry-run)
python cleanup_empty_companies.py

# Step 3: If confident, clean up old empty companies
python cleanup_empty_companies.py --apply --min-age-days 7

# Step 4: Re-validate to confirm
python validate_companies.py
```

## Preventing the "Already Deleted" Warning

### Option 1: Clear Selection After Delete (Recommended)

Modify the `delete_company` view to redirect without company parameter:

```python
# Current behavior:
return redirect("label_companies")

# This preserves old URL params, causing the warning
```

The view already does this correctly. The warning appears when you manually refresh or use browser back button.

### Option 2: User Behavior (Simplest)

After deleting a company:
1. Don't use browser back button
2. Don't manually refresh the page
3. Click on the "Label Companies" link in the sidebar instead

### Option 3: JavaScript Enhancement (Advanced)

Add JavaScript to remove the `?company=ID` parameter after deletion:

```javascript
// In delete confirmation, after success:
window.location.href = "/label_companies/";  // Clean URL, no params
```

## Database Maintenance Schedule

### Daily
- Monitor application logs for deletion errors

### Weekly  
- Run `python validate_companies.py --verbose`
- Review any warnings or duplicates

### Monthly
- Clean up empty companies older than 30 days
- Merge duplicate company entries
- Review and clean up company_source annotations

### Quarterly
- Full database backup
- Run validation with `--fix-orphans` if needed
- Review and optimize database queries

## Troubleshooting

### "Orphaned ThreadTracking records found"

This is a **critical issue** and shouldn't happen with CASCADE delete.

```bash
# Fix automatically
python validate_companies.py --fix-orphans
```

This will delete the orphaned ThreadTracking records.

### "Messages with invalid company_id"

This is a **critical issue** and shouldn't happen with SET_NULL.

```bash
# Fix automatically
python validate_companies.py --fix-orphans
```

This will set `company=NULL` for affected messages.

### "Duplicate company names"

This is a **data quality issue** but not critical.

**Solution**: Use the merge companies feature in the web UI:
1. Go to Label Companies page
2. Select duplicate companies
3. Click "Merge Selected Companies"
4. Choose which company to keep as canonical

### "Companies with no messages or threads"

This is **informational** - companies might be legitimate placeholders.

**Review before deletion**:
- Check if recently created (might receive messages soon)
- Verify they weren't manually added for tracking purposes
- Use cleanup script with age protection

## Technical Details

### Database Queries Used

The validator performs these key checks:

```python
# Orphaned ThreadTracking
ThreadTracking.objects.filter(company__isnull=True)

# Invalid company references (messages)
msg.company_id not in valid_company_ids

# Duplicates
Company.objects.values("name").annotate(count=Count("id")).filter(count__gt=1)

# Empty companies
Message.objects.filter(company=company).count() == 0 and
ThreadTracking.objects.filter(company=company).count() == 0
```

### Performance Considerations

- Validation runs efficiently even with 10,000+ companies
- Uses Django ORM with select_related/prefetch_related where appropriate
- Transaction-safe deletions prevent partial failures
- Indexes on foreign keys ensure fast lookups

## Summary

The "already deleted" warning is **not a bug** - it's expected behavior when URLs reference deleted companies. Your database integrity is protected by:

1. **Foreign key constraints** (CASCADE and SET_NULL)
2. **Validation script** (detects real issues)
3. **Safe cleanup tools** (dry-run by default)
4. **Exception handling** (graceful error messages)

Use these tools regularly to maintain a healthy database!
