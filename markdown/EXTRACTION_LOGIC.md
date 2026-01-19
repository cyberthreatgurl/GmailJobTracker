# EXTRACTION_LOGIC.md

## Overview

This document outlines how company names, job titles, job IDs, and message labels are extracted and classified from Gmail messages.

---

## Message Label Classification Pipeline

### Architecture

The classification pipeline consists of **early detection checks** → **ML + rule-based classification** → **override logic** → **final label assignment**.

### 1. Early Detection Checks (Highest Priority)

These checks run **before** pattern matching and return immediately if matched:

#### Assessment Completion Notifications → `other`
- **Subject line only**: `\bassessments?\s+complete\b`
- **Subject line only**: `\bassessment\s+(?:completion\s+)?status\b`
- **Why**: Prevents "as part of your job application" in body from causing false `job_application` label
- **Example**: "Assessments complete for SUPERVISORY IT SPECIALIST" → `other`

#### Incomplete Application Reminders → `other`
- `\bstarted\s+applying\b.*\bdidn't\s+finish\b`
- `\bdon't\s+forget\s+to\s+finish\b.*\bapplication\b`
- `\bpick\s+up\s+where\s+you\s+left\s+off\b`
- **Why**: These are nudges, not application confirmations

#### Prescreen Detection → `prescreen` (BEFORE scheduling language)
- `\bphone\s*screen\b` - "Phone Screen" in subject
- `\bpre-?screen\b` - "Prescreen" or "Pre-screen"
- `\bprescreening\b` - "Prescreening"
- `\bscreening\s+call\b` - "Screening call"
- `\binitial\s+(?:phone\s+)?screen\b` - "Initial screen" or "Initial phone screen"
- `\bbrief\s+phone\s+call\b` - "Brief phone call"
- **Why**: Phone screens are preliminary, not full interviews. Checked BEFORE scheduling language to avoid misclassifying "Schedule Your Phone Screen" as `interview_invite`
- **Example**: "Schedule Your Phone Screen for Senior Cyber Intelligence Analyst" → `prescreen`

#### Early Scheduling Detection → `interview_invite` (AFTER prescreen check)
- `let\s+me\s+know\s+when\s+you(?:'re|are)?\s+available`
- `available\s+for\s+(?:a\s+)?(?:call|phone\s+call|conversation)`
- `would\s+like\s+to\s+discuss\s+(?:the\s+position|this\s+role)`
- `schedule\s+(?:a\s+)?(?:call|time|conversation|interview)`
- **Why**: True interview invites with scheduling language should override generic application wording

#### Early Rejection Detection → `rejection`
- All rejection patterns checked before application patterns
- **Why**: Prevents "thank you for applying... but we're moving forward with others" from matching as application

#### Early Referral Detection → `referral`
- `has\s+referred\s+you|employee\s+referral|internal\s+referral`
- `referred\s+to\s+you\s+by|referred\s+by|referral\s+from`
- **Why**: Prevents employee referrals from being classified as job applications

#### Explicit Application Confirmation → `job_application`
- `we\s+have\s+received\s+your\s+application`
- `thanks?\s+(?:you\s+)?for\s+applying`
- `application\s+received|your\s+application\s+has\s+been\s+(?:received|submitted)`
- **Why**: ATS confirmations should be labeled as applications even if they contain ambiguous phrasing

### 2. Pattern Matching with Exclusions

After early checks, the system iterates through labels in **priority order**:

```python
for label in (
    "offer",              # Most specific: compensation, package
    "rejection",          # Already checked in early detection
    "head_hunter",        # Recruiter blasts
    "noise",              # Newsletters/OTP/promos
    "job_application",    # Application confirmations/status
    "interview_invite",   # Scheduling/availability
    "other",              # Generic catch-all
    "referral",           # Referrals/intros
    "ghosted",
    "blank",
):
```

#### Pattern Exclusions (`message_label_excludes`)

If a pattern matches, exclusions are checked **before** accepting the label:

- **`noise` excludes**: Application/interview/rejection keywords prevent noise classification
- **`head_hunter` excludes**: ATS markers, automated emails, application confirmations
- **`referral` excludes**: Newsletters, legal case references, transaction receipts
- **`rejection` excludes**: "we have received your application" (prevents false rejections)
- **`application` excludes**: Incomplete application reminders (handled by early checks)
- **`interview_invite` excludes**: ATS markers, automated responses, application confirmations

**Example**: Message matches `noise` pattern "newsletter" BUT also matches exclusion "interview" → Skip noise, continue to next label.

### 3. Override Logic (Post-Classification)

After initial ML + rule classification, several overrides may apply:

#### Internal Recruiter Override
- **Condition**: ML label = `head_hunter` AND sender domain maps to known company (not in HEADHUNTER_DOMAINS)
- **Action**: 
  - If label = `job_application` → Validate with ATS markers (workday, taleo, icims, indeed, list-unsubscribe)
  - If label = `interview_invite`, `rejection`, `offer` → Keep label, update company
  - Otherwise → Override to `other`
- **Why**: Internal recruiters from company domains should preserve meaningful labels

#### Internal Introduction Override
- **Condition**: Label = `referral` or `interview_invite` AND sender domain matches company domain
- **Detection**: Check for networking language ("like to introduce", "introducing you")
- **Job Referral Check**: Exclude if "employee referral", "has referred you for", "referred you for a position"
- **Action**: If networking intro (not job referral) → Override to `other`
- **Why**: Distinguish employee job referrals from internal networking introductions

#### Personal Domain Override
- **Condition**: Sender domain in `personal_domains.json` (184 domains: gmail.com, yahoo.com, etc.)
- **Action**: Override to `noise`
- **Why**: Messages from personal email domains are typically noise, not job-related

#### User-Sent Message Detection
- **Condition**: Sender matches user's email address
- **Action**: Override to `other` (unless already `noise` from personal domain)
- **Why**: User's own sent messages should be classified as "other"

### 4. Label Upgrade Logic

Some labels are "upgraded" to more specific classifications:

- `response` → Check if actually `job_application` or `interview_invite`
- `blank` → Fallback to `noise` if no other label matches

---

## Company Name Extraction

### Tiered Logic

1. **Tier 1**: Whitelist match from `json/companies.json` (`known_companies`)
2. **Tier 2**: Domain mapping from `json/companies.json` (`domain_to_company`)
3. **Tier 3**: ATS display name fallback (if not a person name)
4. **Tier 4**: Subject line parsing with validation
5. **Tier 5**: ML prediction if still blank

### Domain Mapping Rules

- **Subdomain-aware**: `careers.company.com` → `company.com`
- **HEADHUNTER_DOMAINS**: Known recruiter domains (e.g., `kforce.com`, `akkodis.com`)
- **ATS_DOMAINS**: Applicant tracking systems (e.g., `myworkdayjobs.com`, `icims.com`)
- **JOB_BOARD_DOMAINS**: Job boards (e.g., `indeed.com`, `greenhouse.io`)

### Notes

- Domain inputs are sanitized before lookup
- Final company value is stored in `company_obj` and normalized
- Company validation removes job titles captured as company names

---

## Job Title Extraction

- Uses subject line parsing with pattern matching
- Removes invalid prefixes (defined in `patterns.json → invalid_company_prefixes`)
- Fallback: "job submission for X", "job application for X", "job title is X"
- Future: ML hybrid extraction planned

---

## Job ID Extraction

- Pattern: `(?:Job\s*#?|Position\s*#?|jobId=)([\w\-]+)`
- ATS-specific patterns for Workday, Greenhouse, Lever
- Stored in `job_id` field

---

## Label Summary

### Label Types

- **`offer`**: Job offer received
- **`rejection`**: Application rejected or position closed
- **`interview_invite`**: Interview scheduled or requested
- **`job_application`**: Application submitted or received
- **`head_hunter`**: External recruiter message
- **`referral`**: Employee referral or networking introduction
- **`noise`**: Newsletters, OTPs, promotions, personal domain messages
- **`other`**: Progress updates, assessment completions, misc correspondence
- **`ghosted`**: No response from company
- **`blank`**: No classification (fallback to noise)

### Priority Order

1. Early subject-line checks (assessment, incomplete apps, scheduling)
2. Early rejection/referral detection
3. Explicit application confirmation
4. Pattern matching with exclusions (offer → rejection → head_hunter → noise → application → interview → other)
5. Override logic (internal recruiter, personal domain, user-sent)
6. Upgrade logic (response → more specific label)