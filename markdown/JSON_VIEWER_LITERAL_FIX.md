# JSON File Viewer - Literal Character Preservation Fix

## Issue
The JSON file viewer was converting special characters in regex patterns when saving, corrupting the patterns.

### Example Problem:
When entering a regex pattern like:
```
\b(hello|world)\b
```

It was being saved as:
```
&lt;b&gt;(hello|world)&lt;/b&gt;
```

This happened because `html.escape()` was being called on regex patterns, converting:
- `<` → `&lt;`
- `>` → `&gt;`
- `&` → `&amp;`
- `"` → `&quot;`
- `'` → `&#x27;`

## Fix Applied

Updated `sanitize_string()` function in `tracker/views.py`:

### Before:
```python
def sanitize_string(value, max_length=200, allow_regex=False):
    # ... validation ...
    value = html.escape(value)  # ❌ Always escaped, even for regex
    # ... more validation ...
    return value
```

### After:
```python
def sanitize_string(value, max_length=200, allow_regex=False):
    # ... validation ...
    
    # For regex patterns, validate but DON'T html-escape
    if allow_regex:
        is_valid, error = validate_regex_pattern(value)
        if not is_valid:
            return None
        return value  # ✅ Return literal characters for JSON storage
    
    # For non-regex strings, HTML escape to prevent XSS
    value = html.escape(value)
    return value
```

## How It Works Now

1. **User enters regex pattern** in the JSON file viewer textarea:
   ```
   \b(referral|referred|recommend\syou)\b
   ```

2. **Pattern is validated** for security (ReDoS, length, dangerous patterns)

3. **Pattern is saved to JSON** with literal characters preserved:
   ```json
   {
     "message_labels": {
       "referral": [
         "\\b(referral|referred|recommend\\syou)\\b"
       ]
     }
   }
   ```

4. **Django template auto-escapes** when displaying in HTML (safe for viewing)

5. **Pattern is used directly** by regex engine without conversion

## Security Maintained

The fix still maintains security by:
- ✅ Validating regex patterns with `validate_regex_pattern()`
- ✅ Blocking code injection attempts (`<script`, `eval(`, etc.)
- ✅ Blocking path traversal (`../`, `%2e%2e`)
- ✅ Blocking null bytes (`\x00`)
- ✅ Length limits (max 500 chars for regex)
- ✅ Preventing ReDoS with complexity checks
- ✅ Template auto-escaping for XSS prevention

## What You Can Now Do

### Edit Patterns with Literal Characters
Enter patterns exactly as they should appear in JSON:

```
\bhello\b|goodbye\sworld|\d{3}-\d{4}
```

### Use Standard Regex Special Characters
All regex special characters work correctly:
- `\b` - word boundary
- `\s` - whitespace  
- `\d` - digit
- `|` - alternation (OR)
- `()` - grouping
- `[]` - character class
- `.` - any character
- `*`, `+`, `?` - quantifiers

### JSON Escaping Still Required
Remember that in JSON files, backslashes are escaped:
- Regex: `\s` → JSON: `\\s`
- Regex: `\b` → JSON: `\\b`

But when entering in the web form, you only need to type the regex as-is:
- Type in form: `\b(hello|world)\b`
- Saved to JSON: `"\\b(hello|world)\\b"`

## Testing

To verify the fix:

1. Go to `/admin/json_file_viewer/`
2. Enter a pattern with special characters:
   ```
   \b(referral|referred|recommend\syou)\b
   ```
3. Click "💾 Save Patterns"
4. Reload the page
5. Verify the pattern displays exactly as entered (no `&lt;`, `&gt;`, etc.)
6. Check `json/patterns.json` to confirm literal characters with proper JSON escaping:
   ```json
   "\\b(referral|referred|recommend\\syou)\\b"
   ```

## Related Files

- `tracker/views.py` - `sanitize_string()` function (line ~1914)
- `tracker/templates/tracker/json_file_viewer.html` - Form template
- `json/patterns.json` - Pattern storage
- `markdown/PATTERN_SYNTAX_QUICK_REF.md` - Pattern syntax guide
