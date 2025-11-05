# Noise Message Company Handling - Changes Summary

## Issue
Noise messages (spam, headhunters, irrelevant notifications) were being associated with companies in the database. This polluted company metrics and created misleading data.

## Solution
Implemented comprehensive logic to ensure noise messages NEVER have companies assigned, across all code paths:

## Files Modified

### 1. `tracker/models.py` - Message Model
**Change**: Added `save()` override to automatically clear company for noise messages
**Location**: Line 99-103
**Purpose**: Catches any manual labeling in Django admin or other direct model saves

```python
def save(self, *args, **kwargs):
    """Override save to ensure noise messages have no company."""
    # Clear company for noise messages
    if self.ml_label == "noise":
        self.company = None
        self.company_source = ""
    super().save(*args, **kwargs)
```

### 2. `parser.py` - Re-ingestion Logic
**Change**: Updated re-ingestion block to explicitly clear company for noise messages
**Location**: Line 1074-1081
**Purpose**: Ensures messages re-classified as noise have their company cleared

**Before**:
```python
if company_obj:
    existing.company = company_obj
    existing.company_source = company_source
```

**After**:
```python
# Update company (including clearing it for noise messages)
if skip_company_assignment:
    # Noise messages should have no company
    existing.company = None
    existing.company_source = ""
elif company_obj:
    # Normal messages get the resolved company
    existing.company = company_obj
    existing.company_source = company_source
```

### 3. `tracker/management/commands/reclassify_messages.py`
**Change**: Added logic to clear company when re-classifying as noise
**Location**: Line 68-80
**Purpose**: Ensures bulk re-classification clears companies for noise messages

**Before**:
```python
msg.ml_label = new_label
msg.confidence = new_conf
msg.save(update_fields=["ml_label", "confidence"])
```

**After**:
```python
msg.ml_label = new_label
msg.confidence = new_conf

# Clear company for noise messages
if new_label == "noise":
    msg.company = None
    msg.company_source = ""
    msg.save(
        update_fields=[
            "ml_label",
            "confidence",
            "company",
            "company_source",
        ]
    )
else:
    msg.save(update_fields=["ml_label", "confidence"])
```

## Files Created

### 4. `scripts/cleanup_noise_companies.py`
**Purpose**: One-time cleanup script to set company=None for existing noise messages
**Status**: Database was already clean (0 noise messages with companies found)

### 5. `tests/test_noise_company_handling.py`
**Purpose**: Comprehensive test suite for noise+company handling
**Tests**:
- ✅ Noise messages created with company=None
- ✅ Model save() override clears company when ml_label changes to "noise"
- ✅ Database integrity check (no existing noise+company associations)

## Logic Flow

### New Message Ingestion
```
Email → ML Classification → label = "noise"
                                    ↓
                          skip_company_assignment = True
                                    ↓
                             company_obj = None
                                    ↓
                    Message.objects.create(company=None)
                                    ↓
                            Message.save() override
                                    ↓
                         ✓ company remains None
```

### Re-ingestion (Existing Message)
```
Existing Message → Re-classify → label = "noise"
                                        ↓
                             skip_company_assignment = True
                                        ↓
                    if skip_company_assignment:
                        existing.company = None
                        existing.company_source = ""
                                        ↓
                              existing.save()
                                        ↓
                             ✓ company cleared
```

### Manual Admin Labeling
```
Admin UI → Change ml_label to "noise" → msg.save()
                                              ↓
                                  Message.save() override
                                              ↓
                                   if ml_label == "noise":
                                       self.company = None
                                       self.company_source = ""
                                              ↓
                                       super().save()
                                              ↓
                                       ✓ company cleared
```

### Bulk Re-classification Command
```
python manage.py reclassify_messages
        ↓
    For each message:
        new_label = predict_subject_type()
        ↓
    if new_label == "noise":
        msg.company = None
        msg.company_source = ""
        msg.save(update_fields=[..., "company", "company_source"])
        ↓
    ✓ company cleared
```

## Verification

### Pre-deployment Check
```powershell
python check_noise_companies.py
# Output: ✓ No noise messages have companies assigned. Database is clean!
```

### Post-deployment Test
```powershell
python tests/test_noise_company_handling.py
# Output: ✅ ALL TESTS PASSED!
```

## Impact

### Before
- Noise messages polluted company metrics
- Dashboard showed spam/headhunter companies
- mark_ghosted command needed explicit `.exclude(ml_label="noise")`
- Metrics required manual noise exclusion in every query

### After
- Noise messages have `company=None`
- Dashboard naturally excludes noise (no company to display)
- Company-based queries automatically skip noise
- Data integrity enforced at model level

## Related Changes
This change complements previous work:
1. `tracker/management/commands/mark_ghosted.py` - Already excludes noise via `.exclude(ml_label="noise")`
2. `tracker/views.py` (dashboard) - Already excludes noise from all breakdown queries
3. `parser.py` - Already has `skip_company_assignment = label_guard == "noise"` guard

## Rollback Procedure
If needed, revert changes to:
1. `tracker/models.py` - Remove `save()` override
2. `parser.py` - Revert to original re-ingestion logic
3. `tracker/management/commands/reclassify_messages.py` - Remove noise company clearing

No database migration needed - changes are code-only.

## Testing Checklist
- [x] Parser creates noise messages with company=None
- [x] Re-ingestion clears company for noise messages
- [x] Manual admin labeling clears company for noise messages
- [x] Bulk reclassification clears company for noise messages
- [x] Database contains no noise messages with companies
- [x] Dashboard excludes noise from metrics
- [x] mark_ghosted command excludes noise

## Release Notes
**Feature**: Noise Message Company Exclusion
**Type**: Data Integrity Enhancement
**Impact**: Noise messages (spam, headhunters, irrelevant notifications) no longer associate with companies, ensuring clean metrics and accurate company tracking.

**For Users**: The dashboard will now show more accurate company statistics, as spam and irrelevant messages are properly excluded from all company-based metrics.

**For Developers**: `Message.ml_label="noise"` now automatically enforces `company=None` at the model level, eliminating the need for manual exclusions in queries.
