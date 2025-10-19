# Company Message Linking Fixes - Summary

## Problem

Multiple messages were incorrectly linked to the wrong companies due to early ingestion data quality issues.

## Fixes Applied

### 1. Initial Discovery: "rejection" Company (ID 35)

**Issue**: Company ID 35 was named "rejection" (a label, not a company)
**Messages affected**: 4 messages incorrectly linked to this fake company
**Resolution**:

- Initially moved all 4 messages to Anthropic (ID 327)

- Deleted invalid "rejection" company record
- **Status**: Later discovered 2 of these messages were wrong and needed re-linking

### 2. CareFirst Message Fix (Message ID 80)

**Issue**: Message about CareFirst job was incorrectly linked to Anthropic

**Message**: "Thank you for your interest in Job ID:20657 - Cyber Security Director (Hybrid)"

**Sender**:

<careers-noreply@carefirst.com>

**Resolution**:

- Moved from Anthropic (ID 327) to CareFirst (ID 326)

- Also updated Message ID 137 from old CareFirst company (ID 57) to canonical CareFirst (ID 326)
- **Result**: CareFirst now has 2 messages correctly linked

### 3. Dragos Message Fix (Message ID 79)

**Issue**: Message about Dragos job was incorrectly linked to Anthropic

**Message**: "Follow-up on Dragos Application"
**Sender**: <no-reply@dragos.com>

**Resolution**:

- Moved from Anthropic (ID 327) to Dragos (ID 149)

- **Result**: Dragos now has 2 messages correctly linked

## Final State

### Anthropic (ID 327)

**Correctly linked messages**: 2

1. Message 336: "Anthropic Follow-Up for Security Engineer: Detection and Response"
sender: <no-reply@appreview.gem.com>

2. Message 344: "Thank you for applying to Anthropic"
sender: <no-reply@us.greenhouse-mail.io>

### CareFirst (ID 326)

**Correctly linked messages**: 2

- Message 80: "Thank you for your interest in Job ID:20657 - Cyber Security Director (Hybrid)"

- Message 137: "Thank you for applying for this Job!"

### Dragos (ID 149)

**Correctly linked messages**: 2

- Message 79: "Follow-up on Dragos Application"

- (1 other message already correctly linked)

## Scripts Created

- `fix_anthropic_messages.py` - Initial fix for messages linked to -    rejection" company
- `check_bad_company.py` - Verification and deletion of bad company
- `find_bad_companies.py` - Scan for other companies with label-like names
- `fix_carefirst_message.py` - Fix CareFirst message linking
- `fix_dragos_message.py` - Fix Dragos message linking

## Root Cause

Early ingestion logic had less robust company extraction, causing:

1. Labels to be stored as company names

2. Messages to be incorrectly grouped by weak signal matching

3. Need for manual cleanup of company references

## Prevention

Current extraction logic (4-tier fallback with validation) should prevent these issues:

1. Known whitelist matching

2. Domain mapping with ATS awareness

3. ML prediction with confidence thresholds

4. Body regex with invalid company name filtering

## Result

✅ All messages now correctly linked to their proper companies
✅ Invalid company record removed
✅ Label companies page will now show correct message counts
✅ No other data quality issues found in company table
