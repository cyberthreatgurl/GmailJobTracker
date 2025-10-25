# Job Alert Label Removal - Complete Summary

**Date**: 2025-01-XX  
**Reason**: The `job_alert` label was deprecated as job alert messages are better classified as `noise` for simplicity and consistency.

---

## ✅ Files Updated (Code & Config)

### Core Python Files
1. **`parser.py`**
   - Removed `"job_alert": ["job_alert"]` from `LABEL_MAP` dictionary
   - Removed comment reference to job_alert

2. **`tracker/views.py`**
   - Removed `job_alert` from `LABEL_SYNONYMS` dict
   - Removed from `allowed_labels` set
   - Removed from fallback series generation
   - Removed from message label choices in `label_applications` view

3. **`train_model.py`**
   - Removed `job_alert` from weak labeling patterns dictionary

4. **`ml_subject_classifier.py`**
   - Removed from priority order in `rule_label()` function
   - Updated default fallback in `ignore_labels` from `["noise", "job_alert", "head_hunter"]` to `["noise", "head_hunter"]`

### Configuration Files
5. **`json/patterns.json`**
   - **Removed entire `job_alert` label block** from `message_labels` section
   - **Added** `"ignore_labels": ["noise", "head_hunter"]` field for clarity

6. **`json/plot_series.json`**
   - Removed `job_alert` series entry
   - Now contains: `job_application`, `interview_invite`, `rejected`, `ghosted`

### Templates
7. **`tracker/templates/tracker/dashboard.html`**
   - Removed all job_alert references from chart and UI

8. **`tracker/templates/tracker/json_file_viewer.html`**
   - Removed `job_alert` from pattern editor label dropdown

### Management Commands
9. **`tracker/management/commands/compare_gmail_labels.py`**
   - Updated `load_ignore_labels()` default fallback from `{"noise", "job_alert", "head_hunter"}` to `{"noise", "head_hunter"}`

### Documentation
10. **`README.md`**
    - Changed "7 Message Types" → "6 Message Types"
    - Removed `job_alert` from the list

11. **`.github/copilot-instructions.md`**
    - Updated ignore threshold docs: removed `job_alert` reference

---

## 🆕 New Management Command

**File**: `tracker/management/commands/remove_job_alert_label.py`

### Purpose
Clean up database records labeled with `job_alert`.

### Usage
```powershell
# Dry run (show what would change)
python manage.py remove_job_alert_label --dry-run

# Set job_alert messages to NULL
python manage.py remove_job_alert_label

# Map job_alert → noise instead of NULL
python manage.py remove_job_alert_label --to-noise
```

### Actions
- Updates `Message.ml_label` for all rows where `ml_label='job_alert'`
  - Default: sets to `NULL`
  - With `--to-noise`: sets to `'noise'`
- Deletes `MessageLabel` row if `label='job_alert'` exists
- Transactional (rollback on `--dry-run`)

---

## 📊 Database Cleanup Status

**Status**: ⚠️ **Pending execution**

**Next Steps**:
1. Run dry-run to preview affected rows:
   ```powershell
   python manage.py remove_job_alert_label --dry-run
   ```

2. Execute cleanup (choose one):
   ```powershell
   # Option A: Set to NULL (allows future reclassification)
   python manage.py remove_job_alert_label

   # Option B: Map to noise (explicit categorization)
   python manage.py remove_job_alert_label --to-noise
   ```

3. **After cleanup**, consider:
   - Retrain model: `python train_model.py`
   - Re-ingest messages for reclassification: `python manage.py reclassify_messages`

---

## 🔍 Remaining References (Non-Critical)

These files contain historical/legacy references that don't affect runtime:

### Model Artifacts (Generated)
- `model/model_info.json` - Contains `job_alert` in historical label list (regenerated after retraining)
- `model/model_audit.json` - Contains `job_alert` in historical training output (regenerated after retraining)

### Backup/Example Files
- `json/patterns.json.backup` - Legacy backup
- `json/patterns.json.example` - Example config
- `json/gmail_label_map.json` - Gmail label mapping (if you still have Gmail labels)
- `json/mailFilters.xml` - Gmail filter export (external config)

### Documentation (Historical)
- `markdown/PATTERN_SYNTAX_QUICK_REF.md`
- `markdown/PATTERN_MIGRATION_GUIDE.md`
- `markdown/PATTERN_MATCHING.md`
- `markdown/PATTERN_FIXER_UPDATE.md`
- `markdown/LABEL_MESSAGES_V2.md`
- `markdown/EXTRACTION_LOGIC.md`
- `markdown/CODE_CLEANUP_SUMMARY.md`

### Scripts & Debug Tools
- `debug_predict.py` - Standalone debug script
- `alias_candidates.py` - Excludes `job_alert` from query (still valid)
- `find_bad_companies.py` - Ignores `job_alert` (still valid)
- `scripts/fix_patterns_simple.py` - Historical pattern fixer
- `scripts/copilot_upload.txt` - Large doc dump for Copilot context

**Recommendation**: Update these if they're actively used, otherwise they can remain as historical artifacts.

---

## ✨ Validation Checklist

After running the cleanup command:

- [ ] No Python syntax errors: `python -m py_compile parser.py ml_subject_classifier.py tracker/views.py`
- [ ] Dashboard loads without errors: Visit `http://localhost:8000/tracker/`
- [ ] Charts render correctly (no `job_alert` series)
- [ ] Pattern editor works: `http://localhost:8000/tracker/json-viewer/`
- [ ] No DB rows with `ml_label='job_alert'`: 
  ```sql
  SELECT COUNT(*) FROM tracker_message WHERE ml_label='job_alert';
  -- Should return 0
  ```
- [ ] Model retraining succeeds: `python train_model.py --verbose`
- [ ] Ingestion works: `python manage.py ingest_gmail --limit-msg <test_msg_id>`

---

## 🎯 Why Remove job_alert?

1. **Simplification**: Job alerts are automated marketing emails, same as generic noise
2. **Low value**: They don't represent actual application activity or company interaction
3. **Reduced complexity**: Fewer labels = simpler model + clearer UI
4. **Better accuracy**: Merging into `noise` improves training data balance

---

## 🚀 Post-Cleanup Actions

1. **Retrain model** (incorporates updated labels):
   ```powershell
   python train_model.py --verbose
   ```

2. **Re-classify existing messages** (optional, updates old predictions):
   ```powershell
   python manage.py reclassify_messages
   ```

3. **Verify dashboard analytics** (ensure counts/charts update correctly):
   - Check rejection/application/interview counts
   - Verify company breakdowns by activity type

4. **Update Gmail filters** (if you have Gmail labels for job_alert):
   - Remove or redirect the Gmail `#job-hunt/job_alert` label
   - Or remap in `json/gmail_label_map.json` to point to `noise`

---

**Summary**: `job_alert` label successfully removed from all active code, configuration, and UI. Database cleanup command ready to execute. Model retraining recommended after cleanup.
