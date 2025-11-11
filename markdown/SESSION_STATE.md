## Session: November 10, 2025

### Current Status
Working on improving newsletter/bulk mail detection and classification accuracy.

### Recent Changes
1. **Header-based Newsletter Detection** (Nov 8-9)
   - Added `header_hints` extraction in `extract_metadata()` 
   - Detects: `is_newsletter`, `is_bulk`, `is_automated`, `is_noreply`, `reply_to`, `organization`
   - Auto-ignores newsletters/bulk BEFORE ML classification

2. **Application Pattern Matching** (Nov 9)
   - Compiled `APPLICATION_PATTERNS` from `patterns.json` at module load
   - Created `is_application_related(subject, body)` function
   - Enhanced patterns to catch variations:
     - Added: `\byour\sapplication\s(?:to|for|at)\b`
     - Added: `\bapplication\supdate\b`, `\bapplication\sstatus\b`
     - Added: `\bprofile\sconfirmation\b`
     - Added: `\bjob\sapplication\b`, `\bapplication\sreceived\b`
     - Added: `\bthank.*(?:interest|applying)\b`
     - Added: `\bcareer\sopportunity\b`, `\btalent\spool\b`
     - Added: `\bcomplete.*application\b`, `\bfinish.*application\b`

3. **Error Handling** (Nov 9)
   - Improved error messages in `mark_newsletters_ignored.py` and `cleanup_newsletters.py`
   - "Invalid id value" → "Message deleted by user or no longer exists in Gmail"

### Known Issues
1. **Newsletter Headers Too Aggressive**
   - ATS systems (Greenhouse, Workday, Lever) add `List-Unsubscribe` to transactional emails
   - Even with application pattern matching, some valid messages flagged as newsletters
   - Example: "Adrian, Thank you from Elastic" is actually a rejection but has newsletter headers
   
2. **Root Problem Identified**
   - Cannot rely solely on headers - companies use them inconsistently
   - Need to prioritize ML + pattern matching OVER header hints
   - Newsletter auto-ignore should be last resort, not first check

### Proposed Solution (Not Yet Implemented)
The todo list below outlines the planned fix:

1. Compile ALL label patterns (rejection, interview, offer, application, noise) at module load
2. Add helper functions to check if subject/body matches any label patterns
3. Revise auto-ignore logic:
   - Newsletter headers alone DON'T auto-ignore
   - Only ignore if: newsletter header AND noise pattern AND no other label patterns match
   - Let ML classification run for messages with newsletter headers
4. Create review command to scan already-ignored messages and reinstate if they match important patterns

### Files Modified
- `parser.py`: Header extraction, application detection, auto-ignore logic
- `patterns.json`: Enhanced application patterns (26 total now)
- `tracker/management/commands/mark_newsletters_ignored.py`: Uses `is_application_related()`
- `tracker/management/commands/cleanup_newsletters.py`: Improved error handling
- `markdown/README.md`: Updated features and commands
- `markdown/DASHBOARD_OVERVIEW.md`: Added header hints system docs
- `markdown/COMMAND_REFERENCE.md`: Comprehensive command documentation (new file)
- `markdown/QUICK_START.md`: Getting started guide (new file)
- `markdown/DOCUMENTATION_INDEX.md`: Central navigation hub (new file)

### Next Session Tasks
1. **Fix Newsletter Detection (Priority 1)**
   - Implement the proposed solution above
   - Test with known edge cases (Elastic rejection, Amentum incomplete application)
   
2. **Amentum Message Parsing Error**
   - Debug "Expecting value: line 138 column 7 (char 5455)" error
   - Message should be labeled "other" (incomplete application reminder)
   
3. **Validation**
   - Re-ingest test messages to verify correct classification
   - Run full newsletter cleanup with new logic
   - Verify no valid applications/rejections are ignored

### Test Cases to Verify
- ✅ "Your application to Armis Security" → application (not ignored)
- ✅ "Parsons Application Update" → application (not ignored)
- ❌ "Adrian, Thank you from Elastic" → rejection (currently ignored, should not be)
- ❓ "Don't forget to finish your application with Amentum" → other (parsing error)
- ✅ "EP188: Servers You Should Know" → noise (correctly ignored)
- ✅ Job alerts from Glassdoor → noise (correctly ignored)
