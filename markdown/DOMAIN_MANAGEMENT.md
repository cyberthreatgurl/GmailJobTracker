# Domain Management

The Domain Management page consolidates email domains from ingested messages and allows labeling into categories: Personal, Company, ATS, Headhunter, and Job Boards.

## Job Boards – Canonical Source

- The canonical list of Job Boards comes from `json/companies.json` under the `job_boards` key.
- The Job Boards badge count uses the size of this JSON list.
- The Job Boards table is augmented to include all domains from the JSON list, even if current message counts are zero.
- Sorting and filtering operate on the augmented list, with counts displayed where available.

## Syncing Data

- Use the Domain Management actions to label domains and write updates back to JSON.
- The "Sync DB to JSON" action captures domains from the database and updates `companies.json` (ATS, Headhunter, Company mappings) while respecting skip lists.

## Testing

- `tests/test_manage_domains_job_board_count.py`: Verifies that Job Boards from JSON appear in the rendered context.
- `tests/test_manage_domains_badge_count.py`: Confirms the badge matches the JSON count.
