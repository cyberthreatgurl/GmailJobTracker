# Dashboard Date Filter Configuration

## Overview
The dashboard supports a configurable default start date for filtering metrics and charts. This is useful when you want to focus on a specific job search period.

## Configuration

### Environment Variable
Set `REPORTING_DEFAULT_START_DATE` in your `.env` file:

```bash
# Set default start date for dashboard (YYYY-MM-DD format)
REPORTING_DEFAULT_START_DATE=2025-01-01
```

### How It Works

1. **Backend Processing** (`tracker/views.py`):
   - Reads `REPORTING_DEFAULT_START_DATE` from environment
   - Parses date in `YYYY-MM-DD` format
   - Uses the **later** of:
     - Configured start date
     - Earliest application/message date in database
   - Passes to template as `reporting_default_start_date`

2. **Frontend Display** (`dashboard.html`):
   - JavaScript reads `reporting_default_start_date` from template
   - Sets initial value of date range picker
   - Filters all charts and company breakdowns to this date range
   - User can still adjust date range manually

### Use Cases

1. **Focus on Current Job Search**
   ```bash
   # Show only data from Jan 1, 2025 onwards
   REPORTING_DEFAULT_START_DATE=2025-01-01
   ```

2. **Quarter-Based Reporting**
   ```bash
   # Q1 2025
   REPORTING_DEFAULT_START_DATE=2025-01-01
   ```

3. **Exclude Old Data**
   ```bash
   # Ignore test/old applications from previous year
   REPORTING_DEFAULT_START_DATE=2025-01-01
   ```

### Behavior

- **If NOT set**: Dashboard shows all data from earliest message/application
- **If set to future date**: Falls back to earliest available date
- **If set to past date**: Uses configured date (if data exists)
- **User override**: Date picker always allows manual adjustment

### Example Workflow

1. Edit `.env`:
   ```bash
   REPORTING_DEFAULT_START_DATE=2025-01-01
   ```

2. Restart Django development server:
   ```bash
   python manage.py runserver
   ```

3. Visit dashboard - date range automatically starts at 2025-01-01

4. Adjust manually using date picker if needed

## Testing

To verify the configuration is working:

1. Set the environment variable
2. Restart server
3. Open dashboard
4. Check browser console: `console.log(reportingDefaultStart)`
5. Verify date picker shows your configured date
6. Check charts filter to selected range

## Notes

- Date format **must** be `YYYY-MM-DD` (ISO 8601)
- Invalid dates are silently ignored (falls back to earliest date)
- Changes require server restart to take effect
- Template variable: `{{ reporting_default_start_date }}`
