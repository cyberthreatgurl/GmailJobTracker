# Internal Referral Classification Fix

## Problem
Emails from company employees introducing/referring candidates to join their company were being classified as `interview_invite` instead of `other`. 

**Example:** John Loucaides (john.loucaides@eclypsium.com) introducing Kelly to Stas to discuss joining Eclypsium should be labeled `other` since it's an internal referral, not an external interview invitation.

## Root Cause
The classification pipeline had two separate paths:
1. `parse_subject()` - correctly detected internal referrals and overrode label to `other`
2. `predict_with_fallback()` - returned ML label (e.g., `interview_invite`)

However, `ingest_message()` was using the `predict_with_fallback()` result (`result["label"]`) instead of the potentially overridden label from `parse_subject()` (`parsed_subject["label"]`).

## Solution
Added internal referral override logic in two locations:

### 1. Main Gmail Ingestion (`ingest_message`, line ~1808)
After calling both `predict_with_fallback()` and `parse_subject()`, check if `parse_subject` detected an internal referral and override `result["label"]`:

```python
# If parse_subject detected internal referral and overrode label to 'other', apply to result
if parsed_subject.get("label") == "other" and isinstance(result, dict) and result.get("label") in ("referral", "interview_invite"):
    sender_domain = metadata.get("sender_domain")
    if sender_domain:
        from_company = parsed_subject.get("company") or parsed_subject.get("predicted_company")
        if from_company:
            mapped_domain_company = _map_company_by_domain(sender_domain)
            if mapped_domain_company and mapped_domain_company.lower() == from_company.lower():
                result = dict(result)  # Create mutable copy
                result["label"] = "other"
                if DEBUG:
                    print(f"[INTERNAL REFERRAL] Overriding result label to 'other' for internal referral: {sender_domain} matches {from_company}")
```

### 2. EML File Ingestion (`ingest_message_from_eml`, line ~3146)
Similar override logic for .eml file ingestion path:

```python
# If parse_subject detected internal referral and overrode label to 'other', apply to result
if isinstance(parse_result, dict) and parse_result.get("label") == "other" and ml_label in ("referral", "interview_invite"):
    sender_domain = metadata.get("sender_domain")
    if sender_domain and company:
        mapped_domain_company = _map_company_by_domain(sender_domain)
        if mapped_domain_company and mapped_domain_company.lower() == company.lower():
            ml_label = "other"
            if DEBUG:
                print(f"[EML INTERNAL REFERRAL] Overriding ml_label to 'other' for internal referral: {sender_domain} matches {company}")
```

## Detection Logic (in `parse_subject`, line ~1620)
The internal referral detection is already implemented in `parse_subject()`:

```python
if label in ("referral", "interview_invite") and sender_domain and company:
    company_domain = _map_company_by_domain(sender_domain)
    if company_domain and company_domain.lower() == company.lower():
        body_lower = (body or "").lower()
        if "introduce" in body_lower or "introduction" in body_lower or label == "referral":
            if DEBUG:
                print(f"[DEBUG] Internal referral/introduction detected: sender domain {sender_domain} matches company {company}, overriding to 'other'")
            label = "other"
```

## Conditions for Internal Referral Override
1. ML/rule-based classification is `referral` or `interview_invite`
2. Sender domain exists
3. Company name extracted successfully
4. Sender domain maps to the same company name (case-insensitive)
5. Body contains "introduce"/"introduction" keywords OR label is already "referral"

## Test Results
All test cases pass:

| Test Case | Subject | Sender | Expected Label | Expected Company | Result |
|-----------|---------|--------|----------------|------------------|--------|
| Capital One Rejection | Re: Sr. Information Security Engineer | CapitalOneHRWorkday | rejection | Capital One | ✅ PASS |
| Leidos Interview Invite | Conversation | Yama.Wakman@leidos.com | interview_invite | Leidos | ✅ PASS |
| Eclypsium Internal Referral | Intro Kelly and Stas | john.loucaides@eclypsium.com | other | Eclypsium | ✅ PASS |

## Files Modified
- `parser.py`:
  - Lines 1808-1818: Added internal referral override in `ingest_message()`
  - Lines 3146-3154: Added internal referral override in `ingest_message_from_eml()`
  - Lines 1620-1629: Existing detection logic in `parse_subject()` (already present)

## Related Issues
This fix completes the classification improvements for:
- Capital One company extraction (ATS aliases)
- Capital One rejection pattern matching
- .eml file reingest from Label Messages page
- Leidos company employee emails not marked as noise
- **Internal company referrals labeled as 'other'** ✅
