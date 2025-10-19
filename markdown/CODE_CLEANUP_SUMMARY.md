# Code Cleanup Summary - Hardcoded Data Removal

**Date:** October 19, 2025  
**Objective:** Identify and remove hardcoded lists, sets, and dictionaries that duplicate data already stored in JSON configuration files.

## Issues Found and Fixed

### 1. ✅ `find_bad_companies.py` - Hardcoded Invalid Company Names

**Problem:**

- Lines 15-32 contained hardcoded set of invalid company names (message labels)
- This duplicated the labels already defined in `patterns.json → message_labels`

**Solution:**

- Modified script to load message label keys from `patterns.json`
- Added fallback to minimal set if JSON load fails
- Now references single source of truth instead of maintaining duplicate list

**Files Changed:**

- `find_bad_companies.py` - Now loads from `json/patterns.json`

---

### 2. ✅ `ml_subject_classifier.py` - Hardcoded Regex Patterns

**Problem:**

- Lines 97-133 contained hardcoded regex patterns for message classification:
  - Interview keywords
  - Application confirmation patterns
  - Rejection patterns
  - Job alert patterns
  - Headhunter patterns
  - Noise patterns
- These duplicated patterns already in `patterns.json → message_labels`

**Solution:**

- Removed all hardcoded regex patterns from `rule_label()` function
- Added `_COMPILED_PATTERNS` dictionary that loads and compiles patterns from `patterns.json`
- Function now iterates through configured patterns in priority order
- Maintains same functionality but with single source of truth

**Files Changed:**

- `ml_subject_classifier.py` - Now uses patterns from JSON instead of hardcoded regexes

---

### 3. ✅ `ml_subject_classifier.py` - Hardcoded Ignore Labels

**Problem:**

- Line 183 contained hardcoded set: `ignore_labels = {"noise", "job_alert", "head_hunter"}`
- This was not configurable and required code changes to modify

**Solution:**

- Added new field to `patterns.json`: `"ignore_labels": ["noise", "job_alert", "head_hunter"]`
- Modified `predict_subject_type()` to load ignore labels from configuration
- Falls back to default list if not present in JSON

**Files Changed:**

- `ml_subject_classifier.py` - Loads ignore_labels from patterns
- `json/patterns.json` - Added `ignore_labels` configuration field

---

## Already Correct (No Changes Needed)

### ✅ `parser.py` - Company/Domain Mappings

- `ATS_DOMAINS` - Loaded from `companies.json → ats_domains` ✓
- `KNOWN_COMPANIES` - Loaded from `companies.json → known` ✓
- `DOMAIN_TO_COMPANY` - Loaded from `companies.json → domain_to_company` ✓
- `PATTERNS` - Loaded from `patterns.json` ✓
- `invalid_company_prefixes` - Loaded from `patterns.json → invalid_company_prefixes` ✓

### ✅ `ignore_tester.py`

- `IGNORE_PHRASES` - Loaded from `patterns.json → ignore` ✓

---

## Benefits of These Changes

1. **Single Source of Truth**: All configuration data lives in JSON files
2. **Easier Maintenance**: Update patterns in one place (JSON) instead of multiple Python files
3. **User Configurable**: JSON files can be edited without touching code
4. **Consistency**: Eliminates risk of patterns getting out of sync between files
5. **Testability**: Easier to test with different pattern sets

---

## Testing Recommendations

1. **Verify Classification Still Works:**

   ```powershell
   python -c "from ml_subject_classifier import predict_subject_type; print(predict_subject_type('Interview scheduled for next week'))"
   ```

2. **Test Invalid Company Detection:**

   ```powershell
   python find_bad_companies.py
   ```

3. **Verify Ignore Labels:**

   ```powershell
   python -c "from ml_subject_classifier import predict_subject_type; result = predict_subject_type('Job Alert: New positions'); print(f\"Label: {result['label']}, Ignore: {result['ignore']}\")"
   ```

4. **Run Full Test Suite:**

   ```powershell
   pytest tests/
   ```

---

## Configuration Files Reference

### `json/patterns.json`

- `message_labels` - Regex patterns for each message type
- `invalid_company_prefixes` - Company names to reject
- `ignore_labels` - **NEW** - Labels to auto-ignore
- Top-level patterns: `application`, `rejection`, `interview`, `ignore`, etc.

### `json/companies.json`

- `known` - Whitelist of known company names
- `domain_to_company` - Domain → company mappings
- `ats_domains` - ATS system domains
- `aliases` - Company name aliases

---

## Files Modified

1. `find_bad_companies.py` - Load invalid names from patterns.json
2. `ml_subject_classifier.py` - Load regex patterns and ignore labels from patterns.json
3. `json/patterns.json` - Added `ignore_labels` field

## Lines of Code Removed

- ~40 lines of hardcoded patterns/data
- Replaced with ~15 lines of configuration loading code
- Net: Cleaner, more maintainable codebase
