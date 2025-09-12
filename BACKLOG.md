# Job Tracker Backlog

## Now / Next / Later Roadmap

### **Now** (In Progress)
- [Story 1: Add company/job correlation index](#story-1-add-companyjob-correlation-index)

### **Now** (Active Focus)

- [Story 3: Refine company name extraction](#story-3-refine-company-name-extraction)
- [Story 6: Refine status classification](#story-6-refine-status-classification)

### **Next** (Queued for Upcoming Work)

- [Story 2: Baseline HTML dashboard](#story-2-baseline-html-dashboard)
- [Story 4: Improve job title extraction](#story-4-improve-job-title-extraction)
- [Story 5: Implement job ID extraction](#story-5-implement-job-id-extraction)

### **Later** (Future Enhancements / Nice-to-Haves)

- [Story 7: Security & maintainability foundation](#story-7-security--maintainability-foundation)
- [Story 8: Documentation & onboarding](#story-8-documentation--onboarding)

--

## Epic: Professional Job Tracker Dashboard

As a job seeker, I want a secure, modern dashboard so I can track, visualize, and manage all my job applications in one place.

---

### Story 1: Add company/job correlation index

**Description:**  
As a developer, I want to add a composite index `(company, job_title, job_id)` so the system can group all related messages for visualization.

**Acceptance Criteria:**

- DB schema updated with composite index.
- Historical migration script populates missing values.
- Index creation is idempotent and safe to run multiple times.
- Unit test verifies correlation queries return correct grouped results.

**Security & Documentation:**

- Validate DB inputs to prevent SQL injection.
- Document schema changes in `SCHEMA_CHANGELOG.md` with version/date.
- Include rollback instructions in case of migration failure.

---

### Story 2: Baseline HTML dashboard

**Description:**  
As a user, I want a clean, responsive HTML dashboard to view and filter my applications.

**Acceptance Criteria:**

- Displays applications grouped by `(company, job_title, job_id)`.
- Filters by status, company, date range.
- Responsive layout for desktop and mobile.
- No inline JavaScript; all scripts loaded from vetted sources.
- Tested in at least Chrome, Firefox, and Edge.

**Security & Documentation:**

- Escape all dynamic content to prevent XSS.
- Use HTTPS for all asset loading.
- Document dashboard architecture in `DASHBOARD_OVERVIEW.md`.

---

### Story 3: Refine company name extraction

**Description:**  
As a developer, I want to use sender domain/email to fill in missing company names when auto‑extraction fails.

**Acceptance Criteria:**

- If `company` is empty, lookup from `domain_to_company` mapping.
- Mapping stored in `patterns.json` or DB table for easy updates.
- Unit tests cover fallback logic.

**Security & Documentation:**

- Sanitize domain inputs before lookup.
- Document fallback logic in `EXTRACTION_LOGIC.md`.

---

### Story 4: Improve job title extraction

**Description:**  
As a user, I want accurate job titles extracted from subjects and bodies.

**Acceptance Criteria:**

- Regex + ML hybrid extraction.
- Stopword filtering for generic titles.
- Unit tests with real‑world examples.

**Security & Documentation:**

- Avoid regex patterns that can cause catastrophic backtracking.
- Document extraction patterns and ML model training data sources.

---

### Story 5: Implement job ID extraction

**Description:**  
As a user, I want job IDs extracted from ATS emails.

**Acceptance Criteria:**

- Pattern library for Workday, Greenhouse, Lever, etc.
- Unit tests for each ATS pattern.
- Fallback to `null` if no match.

**Security & Documentation:**

- Validate extracted IDs to avoid injection into queries.
- Document patterns in `EXTRACTION_LOGIC.md`.

---

### Story 6: Refine status classification

**Description:**  
As a user, I want more accurate status detection for applications.

**Acceptance Criteria:**

- Combine keyword rules + ML classification.
- Unit tests for each status type.
- Confidence score stored in DB.

**Security & Documentation:**

- Ensure ML model loading is safe and versioned.
- Document classification logic and training data.

---

### Story 7: Security & maintainability foundation

**Description:**  
As a developer, I want to ensure the codebase follows secure coding and maintainability best practices.

**Acceptance Criteria:**

- Input validation for all external data (Gmail API, DB, dashboard).
- Centralized config for DB path, patterns, and model locations.
- Logging with no sensitive data exposure.
- Unit test coverage ≥ 80%.

**Security & Documentation:**

- Follow OWASP Top 10 guidelines.
- Maintain `SECURITY.md` with threat model and mitigations.
- Maintain `README.md` with setup, run, and test instructions.

---

### Story 8: Documentation & onboarding

**Description:**  
As a future maintainer, I want clear documentation so I can onboard quickly.

**Acceptance Criteria:**

- `README.md` with quick start.
- `CONTRIBUTING.md` with coding standards.
- `CHANGELOG.md` for version history.
- Inline docstrings for all public functions.

**Security & Documentation:**

- Document all security‑relevant decisions.
- Keep docs in sync with code changes.
