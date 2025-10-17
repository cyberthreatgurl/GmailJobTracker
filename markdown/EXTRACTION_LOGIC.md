# EXTRACTION_LOGIC.md

## Overview

This document outlines how company names, job titles, job IDs, and status values are extracted from Gmail messages.

---

## Company Name Extraction

### Tiered Logic

1. **Tier 1**: Whitelist match from `known_companies.txt`
2. **Tier 2**: Heuristic validation via `is_valid_company()`
3. **Tier 3**: Fallback to domain mapping from `patterns.json → domain_to_company`
4. **Tier 4**: ML prediction if still blank or generic

### Notes

- Domain inputs are sanitized before lookup
- Final company value is stored in `company_obj` and `company_job_index`

---

## Job Title Extraction

- Currently uses subject line parsing
- ML hybrid extraction planned (see Story 4 in `BACKLOG.md`)
- Stopword filtering and regex tuning in progress

---

## Job ID Extraction

- Placeholder logic present
- Pattern library for ATS systems (Workday, Greenhouse, Lever) planned
- See Story 5 in `BACKLOG.md`

---

## Status Classification

- Combines keyword rules from `patterns.json` with ML classification
- Confidence score stored in DB
- Status values include: `interview`, `rejection`, `job_alert`, `application`, `follow_up`, `noise`,`referral`,`empty`