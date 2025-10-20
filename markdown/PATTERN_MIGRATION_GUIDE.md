# Pattern Migration Scripts

## Overview

Two scripts are provided to help migrate and fix patterns in `patterns.json`:

1. **`fix_patterns_simple.py`** - Recommended for most users
2. **`migrate_patterns_to_regex.py`** - Advanced consolidation (use with caution)

## Script 1: fix_patterns_simple.py (Recommended)

### What It Does
- ✅ Processes **ALL** pattern sections in `patterns.json`:
  - `message_labels` (main regex patterns)
  - `application`, `rejection`, `interview` (legacy patterns)
  - `ignore`, `response`, `follow_up` (legacy patterns)
- ✅ Fixes escaped spaces: `\ ` → `\s`
- ✅ Removes HTML entities: `&quot;`, `&amp;`, etc.
- ✅ Validates all regex patterns
- ✅ Preserves existing pattern structure
- ✅ Creates timestamped backup before changes

### What It Doesn't Do
- Does NOT consolidate multiple patterns
- Does NOT change pattern logic
- Does NOT add word boundaries automatically

### Usage

#### Dry Run (Preview Changes)
```powershell
python scripts\fix_patterns_simple.py --dry-run --verbose
```

#### Apply Fixes
```powershell
python scripts\fix_patterns_simple.py
```

#### Options
- `--dry-run` - Show changes without saving
- `--verbose` or `-v` - Show detailed before/after for each pattern
- `--input PATH` - Specify custom input file (default: `json/patterns.json`)

### Example Output
```
🔍 Loading patterns from: json\patterns.json

📝 Processing label: referral
  ✅ BEFORE: (referral|referred|&quot;\ connect\ you\ with\b)
     AFTER:  (referral|referred|\sconnect\syou\swith\b)

📊 Statistics:
  ✅ Fixed: 3 patterns
  ⏭️  Unchanged: 49 patterns

✅ Saved fixed patterns to: json\patterns.json
```

### When to Use
- You have escaped spaces (`\ `) in patterns
- You have HTML entities (`&quot;`) from previous edits
- You want to validate all patterns
- You want minimal changes with maximum safety

---

## Script 2: migrate_patterns_to_regex.py (Advanced)

### What It Does
- ✅ All fixes from `fix_patterns_simple.py`
- ✅ Consolidates multiple simple patterns into single OR pattern
- ✅ Escapes regex special characters in plain text
- ✅ Converts plain text with spaces to proper regex

### What It Doesn't Do
- Does NOT consolidate complex regex patterns
- Does NOT modify patterns that already use regex features

### Usage

#### Dry Run (Preview Changes)
```powershell
python scripts\migrate_patterns_to_regex.py --dry-run --verbose
```

#### Apply Migration
```powershell
python scripts\migrate_patterns_to_regex.py
```

#### Options
- `--dry-run` - Show changes without saving
- `--verbose` or `-v` - Show detailed conversion info
- `--input PATH` - Input file (default: `json/patterns.json`)
- `--output PATH` - Output file (default: overwrites input)

### Example Output
```
📝 Processing label: application
  🔄 Consolidated 5 patterns into 1
  ✅ for applying|received your application|...
     -> (for\sapplying|received\syour\sapplication|...)

📊 Migration Statistics:
  ✅ Converted: 15 patterns
  🔄 Consolidated: 6 labels
  ⏭️  Kept as-is: 2 patterns
```

### When to Use
- You have many simple text patterns you want to consolidate
- You want to optimize pattern matching performance
- You understand regex and can verify the consolidated patterns

### Caution
- Review consolidated patterns carefully
- Test in Label Rule Debugger before production use
- May change matching behavior if patterns are consolidated incorrectly

---

## Comparison

| Feature | fix_patterns_simple.py | migrate_patterns_to_regex.py |
|---------|------------------------|------------------------------|
| Fix escaped spaces | ✅ | ✅ |
| Remove HTML entities | ✅ | ✅ |
| Validate patterns | ✅ | ✅ |
| Consolidate patterns | ❌ | ✅ |
| Escape special chars | ❌ | ✅ |
| Risk level | Low | Medium |
| Recommended for | Everyone | Advanced users |

---

## Common Fixes Applied

### Before
```json
{
  "referral": [
    "(referral|referred|&quot;\\ connect\\ you\\ with\\b)"
  ],
  "job_alert": [
    "(job\\ alert|job\\ alerts)"
  ]
}
```

### After (fix_patterns_simple.py)
```json
{
  "referral": [
    "(referral|referred|\\sconnect\\syou\\swith\\b)"
  ],
  "job_alert": [
    "(job\\salert|job\\salerts)"
  ]
}
```

### After (migrate_patterns_to_regex.py with consolidation)
```json
{
  "application": [
    "(for\\sapplying|received\\syour\\sapplication|thank\\syou\\sfor\\syour\\sapplication)"
  ]
}
```

---

## Safety Features

Both scripts include:
- ✅ **Automatic backup** - Creates timestamped backup before changes
- ✅ **Regex validation** - Validates all patterns before saving
- ✅ **Dry-run mode** - Preview changes before applying
- ✅ **Error reporting** - Shows which patterns failed validation
- ✅ **Rollback** - Can restore from backup if needed

### Backup Location
```
json/patterns_backup_YYYYMMDD_HHMMSS.json
```

### Restore from Backup
```powershell
# Copy backup back to original
cp json/patterns_backup_20251019_143000.json json/patterns.json
```

---

## Step-by-Step Migration Guide

### Recommended Workflow

1. **Review current patterns**
   ```powershell
   # View in browser
   http://localhost:8000/admin/json_file_viewer/
   ```

2. **Run dry-run to preview changes**
   ```powershell
   python scripts\fix_patterns_simple.py --dry-run --verbose
   ```

3. **Apply fixes**
   ```powershell
   python scripts\fix_patterns_simple.py
   ```

4. **Test patterns**
   ```powershell
   # Use Label Rule Debugger
   http://localhost:8000/debug/label_rule/
   ```

5. **Optional: Consolidate patterns** (advanced users only)
   ```powershell
   python scripts\migrate_patterns_to_regex.py --dry-run --verbose
   # Review carefully, then:
   python scripts\migrate_patterns_to_regex.py
   ```

6. **Re-ingest messages to apply new patterns**
   ```powershell
   python manage.py ingest_gmail --force --days-back 7
   ```

7. **Retrain ML model** (if patterns changed significantly)
   ```powershell
   python train_model.py --verbose
   ```

---

## Troubleshooting

### Pattern Validation Failed
```
❌ Invalid regex: referral: (hello( -> error: missing ), unterminated subpattern
```
**Solution**: Fix the pattern manually in `json/patterns.json` or restore from backup

### Changes Not Taking Effect
**Solution**: 
1. Restart Django dev server
2. Clear browser cache
3. Re-ingest messages with `--force` flag

### Backup Not Created
**Solution**: Check file permissions on `json/` directory

### Script Errors
```python
SyntaxWarning: invalid escape sequence
```
**Solution**: This is a warning in script comments, safe to ignore. Pattern fixes still work correctly.

---

## Testing Patterns

### Method 1: Label Rule Debugger (Web UI)
1. Navigate to `/debug/label_rule/`
2. Paste a test message
3. See which patterns matched
4. View highlighted words

### Method 2: Python Test
```python
import re

pattern = r"(referral|referred|recommend\syou)"
text = "I'd like to recommend you for this position"

if re.search(pattern, text, re.IGNORECASE):
    print("✅ Pattern matched!")
else:
    print("❌ No match")
```

### Method 3: Command Line
```powershell
python -c "import re; print('Match' if re.search(r'hello\\sworld', 'Hello World', re.I) else 'No match')"
```

---

## Best Practices

1. **Always run dry-run first**
   ```powershell
   python scripts\fix_patterns_simple.py --dry-run
   ```

2. **Keep backups**
   - Scripts auto-create backups
   - Manually backup before major changes
   - Keep at least 3 recent backups

3. **Test incrementally**
   - Fix one label at a time if issues arise
   - Test in Label Rule Debugger after each change
   - Verify with sample messages

4. **Document changes**
   - Keep notes of what patterns were changed
   - Document why certain patterns were consolidated
   - Track pattern performance over time

5. **Use version control**
   ```powershell
   git add json/patterns.json
   git commit -m "Fix: Updated patterns to use standard regex syntax"
   ```

---

## Related Documentation

- **Pattern Syntax**: `markdown/PATTERN_SYNTAX_QUICK_REF.md`
- **Pattern Matching**: `markdown/PATTERN_MATCHING.md`
- **JSON Viewer Fix**: `markdown/JSON_VIEWER_LITERAL_FIX.md`
