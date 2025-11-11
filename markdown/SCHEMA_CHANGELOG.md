# SCHEMA_CHANGELOG.md
## 2025-09-09
- Added `company_job_index` TEXT column to `applications` table.
- Populated from normalized company, job_title, job_id.
- Created index `idx_company_job_index` for fast grouping.