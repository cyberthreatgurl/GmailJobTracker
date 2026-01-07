# Input Validation Documentation

## Overview

GmailJobTracker implements comprehensive input validation at multiple layers to ensure data integrity and security:

1. **HTML5 Browser Validation** (client-side)
2. **Django Form Validation** (server-side)
3. **Django Model Validation** (database-level)

## Validation Rules

### Text Fields

**Allowed Characters**: Alphanumeric characters plus specified special characters

#### Company Names, Aliases
- **Pattern**: `[a-zA-Z0-9\s.,\-&'"()]+`
- **Allowed**: Letters, numbers, spaces, period (.), comma (,), dash (-), ampersand (&), apostrophe ('), quotation marks ("), parentheses ()
- **Examples**:
  - ✅ "Accenture Federal Services"
  - ✅ "O'Reilly Media"
  - ✅ "AT&T Inc."
  - ✅ "Boeing Co., Ltd."
  - ❌ "Company<script>" (no HTML tags)
  - ❌ "Test#Company" (no hash symbols)

#### Job Titles
- **Pattern**: `[a-zA-Z0-9\s.,\-/()&]+`
- **Allowed**: Letters, numbers, spaces, period (.), comma (,), dash (-), forward slash (/), parentheses (), ampersand (&)
- **Examples**:
  - ✅ "Software Engineer II"
  - ✅ "Director, IT/Cloud Services"
  - ✅ "Senior DevOps Engineer (Remote)"
  - ❌ "Engineer@Company" (no @ symbols)

#### Job IDs
- **Pattern**: `[a-zA-Z0-9\-_]+`
- **Allowed**: Letters, numbers, hyphens (-), underscores (_)
- **Examples**:
  - ✅ "JOB-12345"
  - ✅ "REQ_2025_001"
  - ✅ "12345ABC"
  - ❌ "JOB#12345" (no hash symbols)

#### Domain Names (homepage, ATS, domain)
- **Pattern**: `[a-zA-Z0-9.\-]+`
- **Allowed**: Letters, numbers, periods (.), hyphens (-)
- **Examples**:
  - ✅ "company.com"
  - ✅ "sub-domain.company.co.uk"
  - ❌ "company .com" (no spaces)
  - ❌ "company@domain.com" (no @ symbols)

#### Contact Names
- **Pattern**: `[a-zA-Z\s.,\-']+`
- **Allowed**: Letters, spaces, period (.), comma (,), dash (-), apostrophe (')
- **Examples**:
  - ✅ "John Smith"
  - ✅ "Mary O'Brien"
  - ✅ "Dr. Jane Doe, Ph.D."
  - ❌ "John123" (no numbers in names)

#### Thread IDs
- **Pattern**: `[a-zA-Z0-9]+`
- **Allowed**: Letters and numbers only
- **Examples**:
  - ✅ "18d4c2f8a1b2c3d4"
  - ✅ "ABC123XYZ"
  - ❌ "18d4c2f8-a1b2" (no hyphens)

#### Source Field
- **Pattern**: `[a-zA-Z0-9\s.,\-]+`
- **Allowed**: Letters, numbers, spaces, period (.), comma (,), dash (-)
- **Examples**:
  - ✅ "LinkedIn"
  - ✅ "Indeed.com"
  - ✅ "Direct Application"
  - ❌ "Source@Site" (no @ symbols)

#### Search Box
- **Pattern**: `[a-zA-Z0-9\s.,@\-_]+`
- **Allowed**: Letters, numbers, spaces, period (.), comma (,), at sign (@), dash (-), underscore (_)
- **Note**: More permissive to allow searching email addresses and domains

#### Gmail Label Prefix
- **Pattern**: `[a-zA-Z0-9#\-_]+`
- **Allowed**: Letters, numbers, hash (#), dash (-), underscore (_)
- **Examples**:
  - ✅ "#job-hunt"
  - ✅ "#applications_2025"
  - ❌ "#job hunt" (no spaces)

### URL Fields

**Validation**: Django URLValidator with schemes ['http', 'https']

#### Homepage URLs
- **Required Schemes**: http:// or https://
- **Validation**: Django URLField + URLValidator
- **Auto-correction**: Automatically prepends "https://" if missing in views
- **Examples**:
  - ✅ "https://www.company.com"
  - ✅ "http://company.com/careers"
  - ✅ "company.com" (auto-corrected to https://company.com)
  - ❌ "ftp://company.com" (FTP not allowed)
  - ❌ "javascript:alert()" (XSS attempt)

#### Career/Jobs URLs
- **Same validation as homepage URLs**
- **Max Length**: 512 characters
- **Optional**: Can be left blank

### Email Fields

**Validation**: Django EmailField

#### Contact Email
- **Validation**: Standard email format (RFC 5322)
- **Max Length**: 255 characters
- **Examples**:
  - ✅ "john.smith@company.com"
  - ✅ "recruiter+jobs@company.co.uk"
  - ❌ "invalid@" (incomplete domain)
  - ❌ "@company.com" (missing local part)

## Validation Layers

### 1. HTML5 Browser Validation (Client-Side)

**Location**: Template files (`tracker/templates/`)

**Implementation**:
- `type="url"` for URL inputs (homepage_url, career_url)
- `type="email"` for email inputs
- `pattern` attribute for text inputs with regex validation
- `title` attribute for validation error messages
- `required` attribute for mandatory fields

**Benefits**:
- Immediate user feedback
- Reduces server load
- Better UX

**Limitations**:
- Can be bypassed
- Browser-dependent support
- Not a security measure

### 2. Django Form Validation (Server-Side)

**Location**: `tracker/forms.py`

**Implementation**:
- `RegexValidator` for pattern matching
- `URLValidator` for URL fields
- Custom `clean()` methods for complex validation
- Field-level validators on CharField, URLField

**Forms with Validation**:
- `ManualEntryForm`: company_name, job_title, job_id, source
- `UploadEmlForm`: thread_id
- `CompanyEditForm`: career_url, alias

**Benefits**:
- Centralized validation logic
- Reusable validators
- Cannot be bypassed
- Consistent error messages

### 3. Django Model Validation (Database-Level)

**Location**: `tracker/models.py`

**Implementation**:
- Field validators on model fields
- Applied during `model.full_clean()` and `form.is_valid()`
- Last line of defense before database

**Models with Validation**:
- `Company`: name, domain, ats, homepage, contact_name
- `ThreadTracking`: thread_id, job_title, job_id

**Benefits**:
- Enforced at ORM level
- Consistent across all save operations
- Works with Django Admin
- Migration-tracked changes

## Validation Flow

```
User Input (Browser)
    ↓
HTML5 Validation (pattern, type, required)
    ↓ (if valid)
POST Request to Server
    ↓
Django Form Validation (validators, clean methods)
    ↓ (if valid)
Model Instance Creation
    ↓
Model Validation (field validators)
    ↓ (if valid)
Database Save
```

## Error Messages

### User-Facing Messages

**Form Validation Errors**:
- Display inline with red styling
- Shown above form fields
- Clear, actionable messages

**Model Validation Errors**:
- Caught in views
- Converted to user-friendly messages
- Logged for debugging

**HTML5 Validation Errors**:
- Browser's native error bubbles
- Custom `title` attribute messages

### Developer Messages

**Validator Codes**:
- `invalid_company_name`
- `invalid_job_title`
- `invalid_job_id`
- `invalid_domain`
- `invalid_ats`
- `invalid_contact_name`
- `invalid_thread_id`
- `invalid_alias`
- `invalid_source`

## Testing Validation

### Manual Testing

**Test Invalid Input**:
```python
# In Django shell
from tracker.forms import CompanyEditForm

# Test invalid company name
data = {'name': 'Company<script>alert("XSS")</script>'}
form = CompanyEditForm(data)
assert not form.is_valid()
assert 'name' in form.errors

# Test invalid URL
data = {'career_url': 'javascript:alert(1)'}
form = CompanyEditForm(data)
assert not form.is_valid()
assert 'career_url' in form.errors
```

### Automated Testing

**Validator Tests** (`tests/test_validators.py`):
```python
from django.core.exceptions import ValidationError
from tracker.models import Company

def test_invalid_company_name():
    company = Company(
        name='Invalid<script>',
        first_contact=now(),
        last_contact=now()
    )
    with pytest.raises(ValidationError):
        company.full_clean()

def test_valid_company_name():
    company = Company(
        name="O'Brien & Associates, Inc.",
        first_contact=now(),
        last_contact=now()
    )
    company.full_clean()  # Should not raise
```

## Security Considerations

### XSS Prevention

**Validation Blocks**:
- HTML tags: `<script>`, `<iframe>`, `<img>`
- JavaScript: `javascript:`, `onerror=`
- Data URLs: `data:text/html`

**Django Template Escaping**:
- All variables auto-escaped: `{{ company.name }}`
- Explicit escaping: `{{ user_input|escape }}`
- Safe strings marked explicitly: `{{ html_content|safe }}`

### SQL Injection Prevention

**Django ORM Protection**:
- Parameterized queries
- No raw SQL with user input
- Validators prevent malicious input

### Command Injection Prevention

**No Shell Commands**:
- No `os.system()` or `subprocess` with user input
- All file operations use safe paths
- URL scraping isolated in try-except blocks

## Migration History

**Migration 0014** (2026-01-07):
- Added RegexValidator to Company.name
- Added RegexValidator to Company.domain
- Added RegexValidator to Company.ats
- Added URLValidator to Company.homepage
- Added RegexValidator to Company.contact_name
- Added RegexValidator to ThreadTracking.thread_id
- Added RegexValidator to ThreadTracking.job_title
- Added RegexValidator to ThreadTracking.job_id

## Maintenance

### Adding New Validators

1. **Update Model**:
   ```python
   new_field = models.CharField(
       max_length=255,
       validators=[
           RegexValidator(
               regex=r'^[a-zA-Z0-9\s.,\-]+$',
               message='...',
               code='invalid_new_field'
           )
       ]
   )
   ```

2. **Update Form** (if exists):
   ```python
   new_field = forms.CharField(
       validators=[...same as model...]
   )
   ```

3. **Update Template** (if direct input):
   ```html
   <input pattern="[a-zA-Z0-9\s.,\-]+" 
          title="...">
   ```

4. **Create Migration**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **Add Tests**:
   ```python
   def test_new_field_validation():
       ...
   ```

### Updating Existing Validators

1. Modify regex pattern in models.py and forms.py
2. Run `makemigrations` and `migrate`
3. Update template pattern attributes
4. Update documentation (this file)
5. Test with valid and invalid inputs

## Common Issues

### Issue: Existing Data Violates New Validators

**Solution**:
- Run data cleanup script before migration
- Add data migration to fix invalid records
- Temporarily make validators optional during transition

### Issue: Form Valid but Model Validation Fails

**Solution**:
- Ensure form validators match model validators exactly
- Check for custom `clean()` methods modifying data
- Validate with `form.instance.full_clean()` before save

### Issue: Browser Validation Inconsistent

**Solution**:
- Always validate server-side (never rely on client-side only)
- Test in multiple browsers
- Use polyfills for older browsers if needed

## Best Practices

1. **Always validate server-side** - Client-side is UX, not security
2. **Match validators across layers** - Form and model validators should align
3. **Use descriptive error messages** - Help users fix issues
4. **Test edge cases** - Empty strings, max length, special characters
5. **Document regex patterns** - Explain what's allowed and why
6. **Update all layers** - HTML, form, model when changing validation
7. **Create migrations** - Track validator changes in version control
8. **Log validation failures** - Debug unexpected rejections

## Version History

- **v1.0.16** (2026-01-07): Comprehensive input validation implementation
  - Added RegexValidator to all text fields
  - Added URLValidator to URL fields
  - Added HTML5 pattern validation to templates
  - Created migration 0014 for model validators
  - Documented all validation rules and patterns
