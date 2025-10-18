# JSON File Viewer - Security Documentation

## Overview

The JSON File Viewer implements comprehensive security validation to prevent malicious input that could compromise the application. This document details all security measures implemented.

---

## 🔒 Security Threats Addressed

### 1. **Regular Expression Denial of Service (ReDoS)**
**Threat:** Malicious regex patterns with nested quantifiers can cause exponential backtracking, freezing the application.

**Mitigation:**
- Pattern length limited to 500 characters
- Detection of dangerous constructs:
  - Nested lookaheads with quantifiers: `(?=.*)+`
  - Comment groups: `(?#...)`
  - Multiple nested groups with quantifiers
- Complexity check: Maximum 20 quantifiers per pattern
- Regex compilation test before acceptance

**Example Blocked Patterns:**
```regex
(a+)+$              # Nested quantifiers (ReDoS)
(a|a)*b             # Catastrophic backtracking
(?=.*){10,}         # Nested lookahead bomb
```

### 2. **Code Injection**
**Threat:** Malicious code embedded in strings that gets executed by the application.

**Mitigation:**
- HTML escaping all user input
- Blocking dangerous strings:
  - `<script`, `javascript:`, `onerror=`, `onload=`
  - `<?php`, `<%`, `__import__`, `eval(`, `exec(`
- Python code execution keywords blocked

**Example Blocked Input:**
```
<script>alert('XSS')</script>
javascript:void(0)
__import__('os').system('rm -rf /')
```

### 3. **Cross-Site Scripting (XSS)**
**Threat:** Injected JavaScript that runs in other users' browsers.

**Mitigation:**
- All user input HTML-escaped using `html.escape()`
- Script tags and event handlers blocked
- Django's template auto-escaping enabled

**Example Blocked Input:**
```html
<img src=x onerror="alert('XSS')">
<svg onload="alert('XSS')">
```

### 4. **Path Traversal**
**Threat:** Accessing files outside intended directories using `../` sequences.

**Mitigation:**
- Blocking `../` and `..\` in all inputs
- URL-encoded variants blocked: `%2e%2e`
- Absolute paths to JSON files in code

**Example Blocked Input:**
```
../../etc/passwd
..\..\..\windows\system32
%2e%2e%2f%2e%2e%2fetc%2fpasswd
```

### 5. **Null Byte Injection**
**Threat:** Null bytes (`\x00`) can truncate strings and bypass security checks.

**Mitigation:**
- All input checked for null bytes
- Rejected if found

### 6. **SQL Injection**
**Threat:** Malicious SQL in company names could affect database queries.

**Mitigation:**
- Django ORM used (parameterized queries)
- Company names sanitized before database use
- HTML-escaped to prevent stored XSS

**Example Blocked Input:**
```sql
Company'; DROP TABLE companies; --
Company' OR '1'='1
```

### 7. **Denial of Service (DoS)**
**Threat:** Extremely large inputs consume memory/CPU.

**Mitigation:**
- **Length limits:**
  - Regex patterns: 500 characters max
  - Company names: 200 characters max
  - Domains: 253 characters max (RFC standard)
- **Total entry limit:** 10,000 entries across all fields
- **Complexity limits:** Max 20 regex quantifiers

### 8. **Domain Validation**
**Threat:** Invalid or malicious domain names in mappings.

**Mitigation:**
- RFC-compliant domain validation
- Only letters, numbers, dots, hyphens allowed
- Must contain at least one dot (TLD required)
- Max 253 characters (RFC 1035)
- Case-normalized to lowercase

**Valid Domains:**
```
example.com
sub-domain.example.org
my.very.long.domain.name.com
```

**Invalid Domains:**
```
example            # No TLD
-example.com       # Starts with hyphen
example..com       # Double dot
example.com/path   # Contains path
```

---

## 🛡️ Validation Functions

### `validate_regex_pattern(pattern)`
**Purpose:** Validate regex patterns for security issues.

**Checks:**
1. Pattern is non-empty string
2. Length ≤ 500 characters
3. No ReDoS-prone constructs
4. Valid regex (compiles without errors)
5. Complexity ≤ 20 quantifiers

**Returns:** `(is_valid: bool, error_message: str)`

### `sanitize_string(value, max_length, allow_regex)`
**Purpose:** Sanitize all user input strings.

**Checks:**
1. Non-empty string
2. Length within limits
3. HTML-escaped
4. No code injection keywords
5. No path traversal sequences
6. No null bytes
7. Optional regex validation

**Returns:** `sanitized_string` or `None`

### `validate_domain(domain)`
**Purpose:** Validate domain name format.

**Checks:**
1. RFC-compliant format
2. Length ≤ 253 characters
3. Contains at least one dot
4. Only valid characters (alphanumeric, dots, hyphens)
5. Properly formatted labels

**Returns:** `(is_valid: bool, sanitized_domain: str)`

---

## 📋 Input Validation Rules

### Regex Patterns
```python
Max Length: 500 characters
Allowed: Any valid regex without dangerous constructs
Validation: Compiled and tested for ReDoS
Example: r'\b(interview|schedule)\b'
```

### Company Names
```python
Max Length: 200 characters
Allowed: Alphanumeric + spaces + common punctuation
Blocked: Code injection keywords, path traversal
Example: "Acme Corp & Associates"
```

### Domain Names
```python
Max Length: 253 characters
Format: RFC-compliant domain (letters, numbers, dots, hyphens)
Example: "example.com", "sub.domain.org"
```

### Company Prefixes
```python
Max Length: 100 characters
Allowed: Alphanumeric + spaces + common punctuation
Example: "Resume", "Job Application"
```

---

## 🔐 Additional Security Measures

### 1. **Authentication Required**
All JSON editing requires login (`@login_required` decorator).

### 2. **CSRF Protection**
Django's CSRF tokens prevent cross-site request forgery.

### 3. **Backup Before Save**
Original files backed up to `.backup` before overwriting.

**Backup files:**
```
json/patterns.json.backup
json/companies.json.backup
```

### 4. **Error Handling**
All exceptions caught and logged, preventing information disclosure.

### 5. **Validation Error Reporting**
Users see count of rejected entries but not sensitive details.

**Example:**
```
⚠️ Validation errors: 3 entries rejected for security reasons
```

### 6. **Atomic Operations**
Files only written if ALL validations pass (no partial updates).

---

## 🚨 Security Incident Response

### If Malicious Input Detected

1. **Input is rejected** - Never stored or executed
2. **Validation error shown** - User sees generic error
3. **Backup preserved** - Original config intact
4. **Application continues** - No crash or DoS

### If Suspicious Activity

1. Check validation error logs
2. Review rejected patterns in validation_errors
3. Investigate user account if patterns of abuse
4. Restore from backup if needed:
   ```bash
   cp json/patterns.json.backup json/patterns.json
   cp json/companies.json.backup json/companies.json
   ```

---

## 🧪 Testing Security

### Manual Testing

```python
# Test ReDoS protection
Pattern: "(a+)+$"
Expected: Rejected (nested quantifiers)

# Test XSS protection
Company: "<script>alert('XSS')</script>"
Expected: Rejected or HTML-escaped

# Test path traversal
Company: "../../etc/passwd"
Expected: Rejected

# Test domain validation
Domain: "example..com"
Expected: Rejected (double dot)

# Test length limits
Pattern: "a" * 501
Expected: Rejected (too long)

# Test null byte
Company: "Acme\x00Corp"
Expected: Rejected
```

### Automated Testing

Add to `tests/test_security.py`:

```python
def test_redos_protection():
    from tracker.views import validate_regex_pattern
    
    # Should reject ReDoS patterns
    is_valid, _ = validate_regex_pattern("(a+)+$")
    assert not is_valid
    
    # Should accept safe patterns
    is_valid, _ = validate_regex_pattern(r"\b(interview)\b")
    assert is_valid

def test_xss_protection():
    from tracker.views import sanitize_string
    
    # Should block script tags
    result = sanitize_string("<script>alert(1)</script>")
    assert result is None

def test_path_traversal():
    from tracker.views import sanitize_string
    
    # Should block path traversal
    result = sanitize_string("../../etc/passwd")
    assert result is None

def test_domain_validation():
    from tracker.views import validate_domain
    
    # Should accept valid domains
    is_valid, domain = validate_domain("example.com")
    assert is_valid
    
    # Should reject invalid domains
    is_valid, _ = validate_domain("example")
    assert not is_valid
```

---

## 📊 Security Audit Checklist

- [x] ReDoS protection implemented
- [x] XSS prevention (HTML escaping)
- [x] Code injection blocking
- [x] Path traversal prevention
- [x] Null byte filtering
- [x] SQL injection protection (ORM)
- [x] DoS mitigation (length/complexity limits)
- [x] Domain validation (RFC-compliant)
- [x] Authentication required
- [x] CSRF protection enabled
- [x] Backup before overwrite
- [x] Error handling (no info disclosure)
- [x] Input sanitization
- [x] Validation error reporting
- [x] Atomic file operations

---

## 🔍 Code Review Focus Areas

When reviewing security changes:

1. **Input validation** - Are all user inputs validated?
2. **Length limits** - Are limits enforced consistently?
3. **Regex compilation** - Are patterns tested before use?
4. **HTML escaping** - Is all output escaped?
5. **Error messages** - Do they leak sensitive info?
6. **File operations** - Are paths absolute and safe?
7. **Backup logic** - Is original data preserved?

---

## 📚 References

- **OWASP Top 10:** https://owasp.org/www-project-top-ten/
- **ReDoS Attacks:** https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS
- **XSS Prevention:** https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
- **Input Validation:** https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html
- **RFC 1035 (DNS):** https://www.rfc-editor.org/rfc/rfc1035

---

## ✅ Summary

The JSON File Viewer implements **defense in depth** with multiple layers of security:

1. **Authentication** - Only logged-in users can access
2. **Input Validation** - All inputs sanitized and validated
3. **Length Limits** - Prevents DoS attacks
4. **Regex Safety** - ReDoS protection
5. **HTML Escaping** - XSS prevention
6. **Domain Validation** - RFC-compliant only
7. **Backup System** - Data preservation
8. **Error Handling** - Graceful failures
9. **CSRF Protection** - Django built-in
10. **Atomic Operations** - All-or-nothing saves

**Result:** Secure JSON editing without compromising application integrity.
