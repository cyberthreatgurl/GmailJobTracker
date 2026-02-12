# Government Contract Awards Integration Proposal

**Version:** 2.0 Major Feature Upgrade  
**Date:** 2026-02-12  
**Status:** AWAITING APPROVAL - DO NOT IMPLEMENT YET

---

## Executive Summary

Expand contract tracking from DoD-only (war.gov) to all federal government contracts by integrating USASpending.gov API. This adds FCEB (Federal Civilian Executive Branch) and other agency contracts alongside existing DoD data.

---

## Scope of Changes

### 1. **Renaming: "Defense Contract Awards" → "Government Contract Awards"**

**Affected Components:**
- Model: `DefenseContract` → Keep name for backward compatibility, update display names only
- View function: `defense_contracts()` → Keep name, update docstrings
- Template: `defense_contracts.html` → Keep filename, update page title/headers
- URL route: `/defense_contracts/` → Keep for backward compatibility
- Management command: `fetch_contracts` → Keep name, add new flag
- Navigation labels: "Defense Contract Awards" → "Government Contract Awards"

**Rationale:** Avoid breaking existing URLs, database migrations, and code references. Update user-facing strings only.

---

## 2. **USASpending.gov API Integration**

### API Endpoint Selection

**Primary Endpoint:** `/api/v2/search/spending_by_award/`

**Why this endpoint:**
- Provides contract-level data with company information
- Supports date range filtering (Oct 2025 onwards = FY2025 Q4)
- Returns award amounts, agency info, recipient details
- JSON response suitable for Django consumption

**Alternative considered:** `/api/v2/awards/` - More detailed but requires award ID lookups (2-step process)

### API Request Parameters

```python
{
    "filters": {
        "time_period": [
            {"start_date": "2025-10-01", "end_date": "2026-12-31"}
        ],
        "award_type_codes": ["A", "B", "C", "D"],  # Contracts only (not grants/loans)
        "agencies": [],  # All agencies (DoD, DHS, DOE, etc.)
    },
    "fields": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Awarding Agency",
        "Awarding Sub Agency",
        "Award Date",
        "Description",
        "Place of Performance City",
        "Place of Performance State",
    ],
    "page": 1,
    "limit": 100,
    "sort": "Award Date",
    "order": "desc"
}
```

**Rate Limiting:** No explicit rate limit documented. Implement 1-second delay between requests.

**Authentication:** None required (public API)

---

## 3. **Data Model Updates**

### Option A: Extend DefenseContract Model (RECOMMENDED)

Add new fields to existing `DefenseContract` model:

```python
class DefenseContract(models.Model):
    # Existing fields remain unchanged...
    
    # NEW FIELDS for USASpending integration
    data_source = models.CharField(
        max_length=20,
        choices=[
            ("war_gov", "War.gov (DoD)"),
            ("usaspending", "USASpending.gov"),
        ],
        default="war_gov",
        help_text="Source of this contract record"
    )
    
    award_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="USASpending Award ID (e.g., CONT_AWD_W912GY22C0021)"
    )
    
    awarding_agency = models.CharField(
        max_length=255,
        blank=True,
        help_text="Top-level agency (e.g., Department of Defense)"
    )
    
    awarding_sub_agency = models.CharField(
        max_length=255,
        blank=True,
        help_text="Sub-agency (e.g., Army Corps of Engineers)"
    )
    
    recipient_duns = models.CharField(
        max_length=20,
        blank=True,
        help_text="Recipient DUNS number for company matching"
    )
    
    place_of_performance_state = models.CharField(
        max_length=2,
        blank=True,
        help_text="Two-letter state code"
    )
    
    class Meta:
        # Update unique constraint to prevent duplicates across sources
        unique_together = [
            ("source_url", "company_name_raw", "contract_number"),  # Existing
            ("data_source", "award_id"),  # NEW: USASpending records
        ]
```

**Migration Path:**
1. Add new fields with `null=True, blank=True`
2. Backfill `data_source="war_gov"` for existing records
3. Run tests
4. Deploy

### Option B: Create Separate Model (NOT RECOMMENDED)

Create `GovernmentContract` model and deprecate `DefenseContract`. 

**Rejected because:**
- Requires complex data migration
- Breaks existing Company FK relationships
- Increases UI complexity (two tables to query)

---

## 4. **Service Architecture**

### New Service Class: `USASpendingService`

**Location:** `tracker/services/usaspending_service.py`

**Responsibilities:**
1. Construct API requests with proper pagination
2. Parse JSON responses into Python dicts
3. Map USASpending fields → DefenseContract fields
4. Handle API errors and retries (3 attempts with exponential backoff)
5. Deduplicate against existing records (by award_id)

**Key Methods:**
```python
class USASpendingService:
    def __init__(self, start_date="2025-10-01", end_date=None):
        """Initialize with FY2025 Q4 start date."""
        
    def fetch_contracts(self, limit=500, agency_codes=None) -> List[Dict]:
        """Fetch contracts from API with pagination."""
        
    def parse_contract(self, raw_data: Dict) -> Dict:
        """Map API response to DefenseContract fields."""
        
    def save_contracts(self, parsed_contracts: List[Dict]) -> Tuple[int, int]:
        """Save to DB, returns (created, skipped) counts."""
        
    def match_company(self, recipient_name: str, duns: str) -> Optional[Company]:
        """Fuzzy match recipient to existing Company records."""
```

### Updated `ContractScraperService`

**No changes needed** - Keep existing war.gov scraping logic intact.

Both services will be called independently by management command.

---

## 5. **Management Command Updates**

### `fetch_contracts` Command Enhancement

**New Flags:**
```bash
# Existing behavior (war.gov only)
python manage.py fetch_contracts --max-articles 5

# NEW: Fetch from USASpending
python manage.py fetch_contracts --source usaspending --limit 100

# NEW: Fetch from both sources
python manage.py fetch_contracts --source all --max-articles 5 --limit 100

# NEW: Agency filtering (USASpending only)
python manage.py fetch_contracts --source usaspending --agencies DOE,DHS,DOD
```

**Implementation:**
```python
class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            choices=["war_gov", "usaspending", "all"],
            default="war_gov",
            help="Data source to fetch from"
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Max contracts to fetch from USASpending (ignored for war_gov)"
        )
        parser.add_argument(
            "--agencies",
            type=str,
            help="Comma-separated agency codes for USASpending (e.g., DOD,DHS)"
        )
        # ... existing args ...
```

---

## 6. **UI/UX Changes**

### Contract Listing Page (`defense_contracts.html`)

**Header Update:**
```html
<h1>Government Contract Awards</h1>
<p class="text-gray-600">Federal contracts from DoD (war.gov) and all agencies (USASpending.gov)</p>
```

**New Filter: Data Source**
```html
<select name="source" id="source-filter">
    <option value="all">All Sources</option>
    <option value="war_gov">War.gov (DoD)</option>
    <option value="usaspending">USASpending.gov</option>
</select>
```

**Table Updates:**
- Add "Source" column (icon: 🏛️ for USASpending, 🎖️ for war.gov)
- Add "Agency" column (shows awarding_agency for USASpending records)
- Keep existing columns: Company, Amount, Branch, Date, Description

**No breaking changes** to existing filters (branch, keyword, date range).

---

## 7. **Company Matching Strategy**

**Challenge:** USASpending uses different company names than war.gov.

**Approach:**
1. **Exact name match** (case-insensitive)
2. **Domain lookup** via `recipient_duns` → external DUNS-to-domain API (future enhancement)
3. **Fuzzy matching** using `thefuzz` library (already in dependencies):
   ```python
   from thefuzz import fuzz
   
   if fuzz.ratio(usaspending_name, company.name) > 85:
       return company
   ```
4. **Manual linking** via admin panel (same as current war.gov flow)

**Security Note:** Never auto-create companies from USASpending data to prevent spam/pollution.

---

## 8. **Testing Strategy**

### Unit Tests (`tests/test_usaspending_service.py`)

1. **Mock API responses** using `responses` library
2. Test field mapping: USASpending JSON → DefenseContract fields
3. Test company matching logic (exact, fuzzy, none)
4. Test duplicate detection (same award_id)
5. Test error handling (API timeout, invalid JSON, missing fields)

### Integration Tests

1. Test management command with `--source usaspending`
2. Test dashboard page renders with mixed data sources
3. Test filtering by source

### Manual Testing Checklist

- [ ] Run `fetch_contracts --source usaspending --limit 10`
- [ ] Verify 10 new records in DB with `data_source=usaspending`
- [ ] Check company FK linkage (some matched, some null)
- [ ] Verify dashboard displays mixed records correctly
- [ ] Test source filter (should isolate war.gov vs USASpending)
- [ ] Test date range filter (Oct 2025+)

---

## 9. **Security Considerations**

### Input Validation

**API Response:**
- Validate all fields against expected types (str, int, Decimal)
- Sanitize HTML in `description` field using `bleach`
- Reject records with missing required fields (award_id, recipient_name)

**User Input:**
- Agency codes: Whitelist only valid codes (DOD, DHS, DOE, etc.)
- Date ranges: Enforce min date = 2025-10-01
- Limit parameter: Cap at 1000 to prevent DoS

### SSRF Protection

USASpending API is a trusted government source, but:
- Use `requests` library with timeout (10 seconds)
- Restrict redirects: `allow_redirects=False`
- Validate response content-type == `application/json`

### SQL Injection

All fields parameterized via Django ORM (no raw SQL).

### XSS Prevention

- Use `{{ variable|escape }}` in templates
- Use `bleach.clean()` for rich text descriptions

---

## 10. **Performance Optimization**

### Pagination

USASpending API returns max 100 records per request. Implement cursor-based pagination:

```python
total_fetched = 0
page = 1
while total_fetched < limit:
    response = self._fetch_page(page)
    contracts.extend(response["results"])
    total_fetched += len(response["results"])
    page += 1
    time.sleep(1)  # Rate limiting
```

### Database Indexes

Add indexes for new query patterns:
```python
class DefenseContract(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["data_source", "article_date"]),  # NEW
            models.Index(fields=["award_id"]),  # NEW
            models.Index(fields=["awarding_agency"]),  # NEW
            # ... existing indexes ...
        ]
```

### Caching

Cache USASpending results for 24 hours (government contracts don't change frequently):
```python
@cache_page(60 * 60 * 24)  # 1 day
def defense_contracts(request):
    # ...
```

---

## 11. **Backward Compatibility**

### URL Routes

**Keep existing:**
- `/defense_contracts/` (view function name unchanged)
- Legacy links from external docs still work

**Add alias (optional):**
- `/government_contracts/` → redirects to `/defense_contracts/`

### Model Name

**Keep `DefenseContract`** - Only update verbose names:
```python
class DefenseContract(models.Model):
    class Meta:
        verbose_name = "Government Contract"
        verbose_name_plural = "Government Contracts"
```

### API Contracts

If any external scripts reference the model, they continue working unchanged.

---

## 12. **Documentation Updates**

Files to update:
- `README.md` - Update feature description and screenshots
- `markdown/COMMAND_REFERENCE.md` - Document new `--source` flag
- `markdown/DASHBOARD_OVERVIEW.md` - Update "Defense Contract Awards" → "Government Contract Awards"
- `.github/copilot-instructions.md` - Update context for AI

---

## 13. **Implementation Phases**

### Phase 1: Foundation (Day 1-2)
1. Create `usaspending_service.py` with API client
2. Add new fields to `DefenseContract` model
3. Write migration + backfill existing records
4. Unit tests for service class

### Phase 2: Integration (Day 3-4)
5. Update `fetch_contracts` command with `--source` flag
6. Add company fuzzy matching logic
7. Integration tests for command

### Phase 3: UI (Day 5)
8. Update template page title/headers
9. Add "Source" filter dropdown
10. Add "Source" and "Agency" columns to table
11. Update dashboard word cloud to include USASpending

### Phase 4: Testing & Polish (Day 6-7)
12. Manual testing with live API
13. Performance testing (1000+ records)
14. Documentation updates
15. Security audit

---

## 14. **Risk Assessment**

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| API schema change | Low | High | Version check in service, graceful fallback |
| Rate limiting | Medium | Medium | Implement 1-second delay, respect HTTP 429 |
| Duplicate records | High | Low | Enforce unique constraints, dedup in service |
| Company mismatch | High | Medium | Allow manual linking in admin, improve fuzzy match |
| Performance degradation | Medium | Medium | Add indexes, pagination, caching |

---

## 15. **Rollback Plan**

If USASpending integration causes issues:

1. **Set `data_source` filter default to `war_gov`** (hides USASpending records)
2. **Disable `--source usaspending` in command** (comment out code)
3. **Revert template changes** (restore "Defense Contract Awards" title)
4. **Keep DB schema** (new fields remain for future use)

No data loss - existing war.gov records unaffected.

---

## 16. **Estimated Effort**

- **Development:** 5-7 days (1 developer)
- **Testing:** 2 days
- **Documentation:** 1 day
- **Total:** ~2 weeks

---

## 17. **Dependencies**

**New Python packages:**
```txt
# requirements-prod.in
thefuzz>=0.20.0  # Fuzzy string matching for company names
```

**Existing packages (no changes):**
- requests (API calls)
- beautifulsoup4 (HTML parsing for war.gov)
- Django ORM (database)

---

## 18. **Open Questions for Review**

1. **Should we create a new URL route `/government_contracts/`** or keep the legacy `/defense_contracts/`?
2. **Company matching threshold:** 85% fuzzy match acceptable, or require manual review?
3. **Default data source filter:** Show "All" or "War.gov only" on first page load?
4. **Do we need DUNS-to-domain lookup** for better company matching, or is fuzzy matching sufficient?
5. **Should we backfill contracts from FY2025 Q1-Q3** (July-Sept 2025) or strictly Oct 2025+?

---

## 19. **Success Criteria**

- [ ] USASpending contracts appear in dashboard alongside war.gov
- [ ] Source filter isolates DoD vs. all-agency contracts
- [ ] At least 70% of USASpending companies auto-link to existing Company records
- [ ] No performance degradation (page load < 2 seconds with 1000 records)
- [ ] Zero breaking changes to existing war.gov functionality
- [ ] All tests pass (unit + integration)

---

## Approval Checklist

**Reviewer:** @ashaw  
**Review Date:** _____________

- [ ] Architecture approach approved
- [ ] Data model changes acceptable
- [ ] UI/UX changes meet requirements
- [ ] Security considerations addressed
- [ ] Performance impact acceptable
- [ ] Open questions resolved
- [ ] Ready to proceed with implementation

**Notes/Feedback:**
_____________________________________________________________________________________
_____________________________________________________________________________________

---

**END OF PROPOSAL - AWAITING APPROVAL**
