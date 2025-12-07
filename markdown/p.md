# Quick Start Guide

Get up and running with GmailJobTracker in minutes.

## Prerequisites

- Python 3.8+
- Gmail account with API access
- Windows, macOS, or Linux

---

## Installation

### 1. Clone and Setup Virtual Environment

```bash
cd c:\Users\kaver\code\GmailJobTracker
python -m venv venv

# Windows PowerShell
.\venv\Scripts\Activate.ps1

# Windows CMD
venv\Scripts\activate.bat

# Linux/Mac
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify Environment

```bash
python check_env.py
```

Should show all checks passing ✅

---

## Gmail API Setup

### 1. Enable Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project: "GmailJobTracker"
3. Enable Gmail API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download `credentials.json`

### 2. Place Credentials

```bash
# Move downloaded file to:
c:\Users\kaver\code\GmailJobTracker\json\credentials.json
```

### 3. First Authentication

```bash
python gmail_auth.py
```

- Browser will open for Gmail authorization
- Click "Allow"
- Token saved automatically to `json/token.json`

---

## Database Setup

### 1. Run Migrations

```bash
python manage.py migrate
```

### 2. Create Admin User

```bash
python manage.py createsuperuser
```

Enter username, email (optional), and password.

---

## Initial Data Import

### 1. Import Known Companies

```bash
python manage.py import_companies json/companies.json
```

### 2. First Email Ingestion

```bash
# Start with last 30 days
python manage.py ingest_gmail --days 30
```

**Expected output**:
```
Fetching messages from last 30 days...
Processing 247 messages...
Batch 1 (1-50)...
✓ Processed: Application to Microsoft - Software Engineer
✓ Processed: Interview Invitation - Google
⊗ Ignored: LinkedIn Weekly Digest (newsletter)
...
=== Summary ===
Total processed: 189
Ignored: 58
Companies found: 42
```

### 3. Clean Up Newsletters (Optional)

```bash
# Preview what would be marked
python manage.py mark_newsletters_ignored --dry-run --limit 100

# Actually mark as ignored
python manage.py mark_newsletters_ignored --limit 100
```

---

## Start the Server

```bash
python manage.py runserver
```

**Visit**: [http://localhost:8000/](http://localhost:8000/)

---

## First Use

### 1. Login to Admin

Navigate to: [http://localhost:8000/admin/](http://localhost:8000/admin/)

Login with superuser credentials.

### 2. Review Companies

Go to: [http://localhost:8000/label-companies/](http://localhost:8000/label-companies/)

- See all companies with message counts
- Test rule patterns
- Fix incorrect company names

### 3. Check Dashboard

Go to: [http://localhost:8000/](http://localhost:8000/)

View:
- Application statistics
- Interview calendar
- Recent activity
- Company breakdown

---

## Daily Usage

### Morning Routine

```bash
# 1. Ingest yesterday's emails
python manage.py ingest_gmail --days 1

# 2. Mark applications with no response
python manage.py mark_ghosted

# 3. Start server (if not running)
python manage.py runserver
```

### Review Dashboard

1. Check new applications
2. Update interview dates
3. Mark rejections
4. Follow up on ghosted applications

---

## Common Tasks

### Re-ingest Specific Email

```bash
python manage.py ingest_gmail --message-id <gmail_msg_id>
```

**Find message ID**: In Gmail, open email → More (⋮) → Show original → Message ID

### Update Classification Rules

1. Edit `parser.py` patterns
2. Test changes:
   ```bash
   python scripts/test_rule_label.py
   ```
3. Re-classify all messages:
   ```bash
   python manage.py reclassify_messages
   ```

### Add New Company Mapping

1. Edit `json/companies.json`:
   ```json
   {
     "domain_to_company": {
       "newcompany.com": "New Company Inc"
     }
   }
   ```
2. Re-ingest recent messages:
   ```bash
   python manage.py ingest_gmail --days 7
   ```

### Export Data

```bash
# Export companies
python manage.py export_companies

# Export labeled messages
python manage.py export_labels
```

---

## Troubleshooting

### Gmail API Quota Exceeded

**Problem**: `429 Too Many Requests`

**Solution**: Wait 60 seconds or use smaller batch sizes:
```bash
python manage.py mark_newsletters_ignored --batch-size 25
```

### Token Expired

**Problem**: `Invalid authentication credentials`

**Solution**: Delete token and re-authenticate:
```bash
rm json/token.json
python gmail_auth.py
```

### Newsletter Still Mislabeled

**Problem**: Newsletter classified as "referral"

**Solution**: Re-ingest with new header analysis:
```bash
python manage.py ingest_gmail --message-id <msg_id>
```

### Company Not Found

**Problem**: Email has no company assigned

**Solutions**:
1. Check sender domain:
   ```bash
   python scripts/check_email_body.py <msg_id>
   ```
2. Add to domain mapping in `json/companies.json`
3. Re-ingest message

### Meeting Labeled as Interview

**Problem**: Teams meeting invite labeled "interview"

**Solution**: Run meeting reclassification:
```bash
python scripts/reclassify_meeting_invites.py
```

---

## Debug Mode

Enable verbose logging to see classification decisions:

```powershell
# Windows PowerShell
$env:DEBUG=1
python manage.py ingest_gmail --message-id <msg_id>

# Linux/Mac
DEBUG=1 python manage.py ingest_gmail --message-id <msg_id>
```

**Output shows**:
- Header analysis results
- Rule pattern matches
- Company extraction steps
- Classification confidence
- Final label decision

---

## Backup

### Before Major Changes

```bash
# Backup database
cp job_tracker.db job_tracker.db.backup

# Backup companies
python manage.py export_companies
```

### Restore from Backup

```bash
# Restore database
cp job_tracker.db.backup job_tracker.db

# Or re-import
python manage.py import_companies json/companies.json.backup
```

---

## Next Steps

### Customize Classification

1. Review `parser.py` patterns
2. Add company-specific rules
3. Adjust confidence thresholds
4. Add new label categories

### Improve Company Extraction

1. Add more domain mappings
2. Add ATS domains
3. Customize body parsing patterns
4. Add organization header fallbacks

### Enhance Dashboard

1. Add custom views in `tracker/views.py`
2. Create new templates in `tracker/templates/`
3. Add filters and search
4. Export reports

---

## Resources

- **Full Documentation**: `markdown/README.md`
- **Command Reference**: `markdown/COMMAND_REFERENCE.md`
- **Dashboard Overview**: `markdown/DASHBOARD_OVERVIEW.md`
- **Classification Logic**: `markdown/EXTRACTION_LOGIC.md`
- **Security**: `markdown/SECURITY.md`
- **Changelog**: `markdown/CHANGELOG.md`

---

## Support

### Check Logs

```bash
# Today's ingestion log
cat logs/tracker-2025-11-08.log

# Django errors
cat logs/django.log
```

### Test Individual Components

```bash
# Test rule labeling
python scripts/test_rule_label.py

# Test ML override
python scripts/test_predict_fallback.py

# Check email content
python scripts/check_email_body.py <msg_id>
```

### Environment Diagnostics

Visit: [http://localhost:8000/admin/environment_status/](http://localhost:8000/admin/environment_status/)

Shows:
- Python version
- Package versions
- Database status
- Gmail API status
- Model files status
- Log file permissions

---

## Tips

1. **Start small**: Ingest 7 days first, then expand
2. **Clean regularly**: Run `mark_newsletters_ignored` weekly
3. **Review manually**: Check `/label-companies/` for mislabeled messages
4. **Backup often**: Before reclassification or cleanup operations
5. **Use dry-run**: Always test with `--dry-run` first
6. **Enable DEBUG**: For troubleshooting classification issues
7. **Check logs**: Daily logs show detailed ingestion steps

---

## Keyboard Shortcuts (Dashboard)

- `Ctrl + /` - Search messages
- `Ctrl + K` - Quick company search
- `Ctrl + N` - New application entry
- `Escape` - Close modal/dialog

---

## Performance

### Optimize Ingestion

```bash
# Process in smaller batches
python manage.py ingest_gmail --days 7

# Then extend
python manage.py ingest_gmail --days 30
python manage.py ingest_gmail --days 90
```

### Database Maintenance

```bash
# SQLite vacuum (shrink database)
python manage.py dbshell
> VACUUM;
> .quit
```

### Clean Old Logs

```bash
# Delete logs older than 30 days (Windows PowerShell)
Get-ChildItem logs/*.log | Where-Object LastWriteTime -lt (Get-Date).AddDays(-30) | Remove-Item

# Linux/Mac
find logs/ -name "*.log" -mtime +30 -delete
```

---

**You're all set! 🚀**

Run `python manage.py runserver` and visit [http://localhost:8000/](http://localhost:8000/) to get started.
