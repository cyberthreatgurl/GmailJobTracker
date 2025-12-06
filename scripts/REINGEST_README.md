# Re-ingestion Scripts for Debugging Company Parsing

## Quick Start

### Fix all "Import" companies
```powershell
# Preview what will be fixed
python scripts/fix_import_company.py --dry-run

# Fix all "Import" messages
python scripts/fix_import_company.py

# Fix first 10 only (for testing)
python scripts/fix_import_company.py --limit 10 --verbose
```

### General re-ingestion (more flexible)
```powershell
# Re-ingest all messages from a specific company
python scripts/reingest_messages.py --company "Import"

# Re-ingest messages from Proofpoint domain
python scripts/reingest_messages.py --domain proofpoint.com --show-changes

# Re-ingest specific message IDs
python scripts/reingest_messages.py --msg-ids abc123def456 xyz789

# Re-ingest messages with "application" in subject (for testing pattern changes)
python scripts/reingest_messages.py --subject-contains "application" --limit 20
```

## Common Workflows

### After fixing a parsing bug:
1. **Test with a few messages first:**
   ```powershell
   python scripts/reingest_messages.py --company "Import" --limit 5 --verbose
   ```

2. **If results look good, process all:**
   ```powershell
   python scripts/reingest_messages.py --company "Import" --yes
   ```

### Find which companies need fixing:
```powershell
# In Django shell
python manage.py shell -c "from tracker.models import Company; [print(f'{c.name}: {c.message_set.count()} messages') for c in Company.objects.all() if c.name in ['Import', 'Resume', 'CV']]"
```

### Check specific email parsing:
```powershell
# Create a test file like test_proofpoint.py
python test_specific_email.py
```

## Script Options

### fix_import_company.py
- `--dry-run` - Preview without making changes
- `--limit N` - Only process first N messages
- `--verbose` - Show each message as it's processed

### reingest_messages.py (More Flexible)
**Filters (at least one required):**
- `--company NAME` - Filter by company name
- `--msg-ids ID [ID ...]` - Filter by Gmail message IDs
- `--domain DOMAIN` - Filter by sender domain
- `--subject-contains TEXT` - Filter by subject text

**Options:**
- `--dry-run` - Preview without making changes
- `--limit N` - Only process first N messages
- `--verbose` - Show each message as it's processed
- `--show-changes` - Show before/after company names
- `--yes` / `-y` - Skip confirmation prompt

## Examples for Current Bug

### The "Import" bug was caused by:
1. CSS `@import` statements in HTML emails being matched by `@` regex
2. Greedy regex patterns capturing too much text (e.g., "Proofpoint - We have received your")

### To fix all affected messages:
```powershell
# Check how many messages are affected
python manage.py shell -c "from tracker.models import Company, Message; c = Company.objects.filter(name='Import').first(); print(f'{Message.objects.filter(company=c).count()} messages' if c else '0 messages')"

# Preview what will be fixed
python scripts/fix_import_company.py --dry-run

# Fix all (with confirmation prompt)
python scripts/fix_import_company.py

# Or use the general script for more control
python scripts/reingest_messages.py --company "Import" --show-changes
```

## Testing Pattern Changes

After modifying regex patterns in `parser.py`, test with:

```powershell
# Create a test file for specific email
python test_proofpoint.py

# Or test pattern directly
python test_company_pattern.py

# Re-ingest a small sample to verify
python scripts/reingest_messages.py --company "Import" --limit 10 --verbose
```

## Troubleshooting

### "No module named 'gmail_auth'"
Make sure you're running from the project root directory.

### "Failed to authenticate with Gmail"
Check that `json/token.json` and `json/credentials.json` exist. If token is expired, delete it and re-run.

### Changes not taking effect
1. Make sure you saved `parser.py`
2. The script uses `force=True` which should bypass cache
3. Check that DEBUG mode is off (or you'll see verbose output from parser)

### Still seeing wrong company after re-ingestion
1. Check the parser logic manually with a test script
2. Verify the pattern matches what you expect
3. Look at the priority order - earlier priorities override later ones
4. Check if the company is in `known_companies` or `domain_to_company` mappings
