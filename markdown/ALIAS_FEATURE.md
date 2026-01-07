# Company Alias Feature

## Overview

The Company Alias feature allows users to define alternative names or abbreviations for companies through the Label Companies page UI. Aliases are stored in `json/companies.json` and used for company name matching and normalization throughout the application.

## Feature Details

### UI Location

The alias input field appears on the Label Companies page (`/label_companies/`) in two contexts:

1. **Creating New Company**: Alias field appears after Career/Jobs URL field
2. **Editing Existing Company**: Alias field appears after Career/Jobs URL field with auto-populated value if an alias exists

### Storage

Aliases are stored in `json/companies.json` under the `aliases` object:

```json
{
  "aliases": {
    "AFS": "Accenture Federal Services",
    "Boeing": "Boeing",
    "BAE": "BAE Systems"
  }
}
```

**Structure**: `{"aliasName": "canonicalCompanyName"}`

### Behavior

#### Loading Aliases
- When editing an existing company, the system performs a reverse lookup in the `aliases` dictionary
- If the company name matches a canonical name, the alias is pre-filled in the form
- If no alias exists, the field remains empty

#### Saving Aliases
- **Add/Update**: If a new alias is entered, it's added to `companies.json`
- **Change**: If the alias is changed, the old alias is removed and the new one is added
- **Remove**: If the alias field is cleared, the existing alias is removed from `companies.json`

#### Validation
- Alias field is optional (not required)
- Maximum length: 255 characters
- Trailing/leading whitespace is automatically trimmed

### Use Cases

1. **Acronyms**: "AFS" → "Accenture Federal Services"
2. **Abbreviations**: "BAE" → "BAE Systems"
3. **Common Names**: "Amazon.jobs" → "Amazon"
4. **Display Names**: "capitalone" → "Capital One"

### Implementation Details

#### Form Field
- **File**: `tracker/forms.py`
- **Field**: `CompanyEditForm.alias` (CharField, non-model field)
- **Properties**:
  - `max_length=255`
  - `required=False`
  - Help text: "Alternative name or abbreviation (e.g., 'AFS' for 'Accenture Federal Services')"

#### View Logic
- **File**: `tracker/views/companies.py`
- **Loading** (lines 285-302): Reverse lookup in aliases dictionary
- **Initializing** (line 762): Add alias to form initial dictionary
- **Saving Existing Company** (lines 740-770): Update/remove alias in companies.json
- **Saving New Company** (lines 886-905): Add alias to companies.json if provided

#### Template
- **File**: `tracker/templates/tracker/label_companies.html`
- **New Company Form** (lines 145-150): Alias field after career_url
- **Existing Company Form** (lines 235-240): Alias field after career_url

### JSON Operations

The alias save logic follows this pattern:

1. **Find Old Alias**: Reverse lookup to find existing alias for company
2. **Update/Add**:
   - If alias input is provided:
     - Remove old alias if it differs from new
     - Add/update new alias mapping
   - If alias input is cleared:
     - Remove old alias if exists
3. **Write to File**: Only write if changes were made (tracked via `changes_made` flag)

### Related Features

- **Domain Mapping**: Similar pattern used for `domain_to_company` mappings
- **Career URL**: Non-model field using same save pattern
- **ATS Domains**: Array-based storage (different from alias key-value structure)

## Testing

### Manual Test Steps

1. **View Existing Alias**:
   - Navigate to `/label_companies/`
   - Select a company with an alias (e.g., "Accenture Federal Services")
   - Verify alias field shows "AFS"

2. **Add New Alias**:
   - Select a company without an alias
   - Enter an alias (e.g., "IBM" for "International Business Machines")
   - Click "Save Changes"
   - Verify `json/companies.json` contains new alias mapping

3. **Update Existing Alias**:
   - Select company with alias
   - Change alias value
   - Click "Save Changes"
   - Verify old alias removed and new alias added in `json/companies.json`

4. **Remove Alias**:
   - Select company with alias
   - Clear alias field
   - Click "Save Changes"
   - Verify alias removed from `json/companies.json`

5. **Create Company with Alias**:
   - Click "🔍 Add Company" and enter homepage URL
   - Fill in company details including alias
   - Click "✅ Create Company"
   - Verify alias saved in `json/companies.json`

### Expected Results

- Alias field appears on both new and existing company forms
- Existing aliases load correctly
- Saving updates companies.json atomically
- Clearing alias removes it from companies.json
- No duplicate aliases (one alias per company)
- Changes persist across page reloads

## Version History

- **v1.0.16** (2026-01-07): Initial implementation of alias UI field

## Future Enhancements

- Multiple aliases per company (comma-separated or array-based)
- Alias validation (check for conflicts with existing company names)
- Bulk alias import/export
- Alias autocomplete suggestions
- Alias usage tracking (show where alias is being used)
