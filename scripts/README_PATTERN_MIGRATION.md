# Pattern Migration Scripts - Quick Start

## TL;DR

Fix patterns in `patterns.json` with one command:

```powershell
# Preview changes
python scripts\fix_patterns_simple.py --dry-run

# Apply fixes
python scripts\fix_patterns_simple.py
```

## What Gets Fixed

- ✅ `\ ` (escaped space) → `\s` (regex space)
- ✅ `&quot;` → removed (HTML entity)
- ✅ Validates all regex patterns
- ✅ Creates backup automatically

## Full Documentation

See: `markdown/PATTERN_MIGRATION_GUIDE.md`
