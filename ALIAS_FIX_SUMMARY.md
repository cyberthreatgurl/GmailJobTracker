# Alias Resolution Fix Summary

## Problem
When emails were ingested with company names that matched existing company aliases, the system was creating duplicate companies instead of using the existing aliased company.

**Example:** Company #200 "CGI Inc." had an alias "CGI", but when an email from CGI was ingested, it created a new Company #201 "CGI" instead of using the existing Company #200.

## Root Cause
The `Company.objects.get_or_create()` calls in `parser.py` were looking up companies by the extracted name without first checking if that name was an alias for an existing company in the `CompanyAlias` model.

## Solution
Added a new helper function `resolve_company_alias()` that:
1. Checks the `CompanyAlias` model for the provided company name (case-insensitive)
2. Returns the canonical company name if an alias is found
3. Returns the original name if no alias exists

Updated all `Company.objects.get_or_create()` calls (7 locations) to first resolve aliases before creating/retrieving companies:

### Locations Updated:
1. **Line 3677** - User-sent message company creation
2. **Line 3988** - Main company assignment section
3. **Line 4016** - User-sent message re-ingestion section
4. **Line 4140** - Re-ingestion non-noise user-initiated message
5. **Line 4557** - New message creation for user-initiated section
6. **Line 5283** - EML file processing section

### Code Changes:
```python
# Before:
company_obj, _ = Company.objects.get_or_create(
    name=company,
    defaults={...}
)

# After:
company = resolve_company_alias(company)
company_obj, _ = Company.objects.get_or_create(
    name=company,
    defaults={...}
)
```

## Testing
Created two test scripts:
1. **test_alias_fix.py** - Verified the `resolve_company_alias()` function works correctly
2. **test_cgi_email.py** - Verified that re-ingesting the CGI email uses Company #200 (CGI Inc.) instead of creating a duplicate

### Test Results:
✓ Alias resolution function correctly resolves "CGI" → "CGI Inc."
✓ Re-ingesting CGI email assigns message to Company #200 (CGI Inc.)
✓ No duplicate company created

## Impact
- All future email ingestion will check aliases before creating companies
- Existing duplicate companies (like #201 "CGI") should be manually merged via the dashboard
- Users can now create aliases to prevent duplicate companies from being created

## Recommendations
1. Review existing companies for duplicates and create aliases for them
2. Consider adding a management command to auto-detect and suggest aliases for similar company names
3. Update the dashboard UI to make alias creation more prominent when viewing company details
