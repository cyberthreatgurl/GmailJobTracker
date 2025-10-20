# Pattern Matching in GmailJobTracker

## Overview
This document explains how pattern matching works in the label rule debugger and message classification system.

**Pattern Syntax: Standard Python Regular Expressions (regex)**

All patterns use **standard Python regex syntax** (Python `re` module) with **case-insensitive** matching. This is a well-documented standard used across many programming languages.

## Standard Regex Syntax Reference

### Basic Matching

| Syntax | Meaning | Example | Matches | Doesn't Match |
|--------|---------|---------|---------|---------------|
| Plain text | Literal match | `hello` | "Hello", "hello world" | "help" |
| `\|` | OR (alternation) | `cat\|dog` | "cat", "dog", "I have a dog" | "bird" |
| `.` | Any character | `c.t` | "cat", "cut", "c3t" | "caat" |
| `\s` | Whitespace (space/tab/newline) | `hello\sworld` | "hello world", "hello  world" | "helloworld" |
| `\b` | Word boundary | `\bhello\b` | "hello world", "say hello" | "hellothere" |

### Quantifiers

| Syntax | Meaning | Example | Matches | Doesn't Match |
|--------|---------|---------|---------|---------------|
| `*` | Zero or more | `hello*` | "hell", "hello", "helloooo" | "hel" |
| `+` | One or more | `hello+` | "hello", "helloooo" | "hell" |
| `?` | Zero or one | `colou?r` | "color", "colour" | "colouur" |

### Grouping

| Syntax | Meaning | Example | Matches |
|--------|---------|---------|---------|
| `()` | Group | `(cat\|dog)s` | "cats", "dogs" |
| `[]` | Character class | `[aeiou]` | Any vowel |

## Common Pattern Examples

### 1. OR Logic (Multiple Alternatives)
```json
"referral": ["referral|referred|refer|recommendation"]
```
Matches: "referral", "referred", "refer", or "recommendation"

### 2. Multi-Word Phrases (with spaces)
```json
"referral": ["recommended\\syou|connect\\syou\\swith"]
```
Matches: "recommended you" or "connect you with" (with actual spaces)

**Note:** Use `\s` for whitespace in regex. In JSON, backslash is escaped, so write `\\s`.

### 3. Word Boundaries (Whole Words Only)
```json
"referral": ["\\bintro\\b|\\bintroduction\\b"]
```
Matches: "intro" or "introduction" as complete words only
Doesn't match: "introspection", "reintroduction"

### 4. Combined Example
```json
"referral": ["(referral|referred|recommend\\syou|\\bintro\\b|connect\\syou\\swith)"]
```
This matches ANY of:
- "referral"
- "referred"  
- "recommend you" (both words with space)
- "intro" (as complete word)
- "connect you with" (all words with spaces)

## Special Value: "None"
When a label has the pattern `"None"`, it will never match. This is used to disable matching for that label.

Example:
```json
"interview": ["None"]
```
This disables interview matching entirely.

## JSON Escaping Rules

**Important:** In JSON files, backslashes must be escaped (doubled).

| Regex Syntax | In JSON | Example |
|--------------|---------|---------|
| `\s` (space) | `\\s` | `"hello\\sworld"` |
| `\b` (word boundary) | `\\b` | `"\\bhello\\b"` |
| `\.` (literal dot) | `\\.` | `"example\\.com"` |
| `\|` (literal pipe) | - | Use inside parentheses: `(a\|b)` |

## Complete Pattern File Example

```json
{
  "message_labels": {
    "referral": [
      "referral|referred|refer|recommendation|recommend\\syou|\\bintro\\b|\\bintroduction\\b|connect\\syou\\swith|connecting\\syou\\swith"
    ],
    "job_alert": [
      "job\\salert|job\\salerts|careercenter@computer\\.org|jobs\\smatches",
      "\\b(cybersecurity|matches)\\b",
      "\\b(saved\\ssearch)\\b",
      "\\b(search\\sresults)\\b"
    ],
    "offer": [
      "\\b(offer|compensation|package|extend|congratulations)\\b"
    ],
    "noise": [
      "\\b(unsubscribe|newsletter|digest|promotion|marketing)\\b"
    ]
  }
}
```

### How These Patterns Work

1. **referral** - Matches if ANY of these appear:
   - "referral", "referred", "refer", "recommendation"
   - "recommend you" (with space)
   - "intro" or "introduction" (as complete words)
   - "connect you with" or "connecting you with" (with spaces)

2. **job_alert** - Has multiple patterns (evaluated separately):
   - Pattern 1: "job alert" OR "job alerts" OR "careercenter@computer.org" OR "jobs matches"
   - Pattern 2: "cybersecurity" OR "matches" (whole words only)
   - Pattern 3: "saved search" (as phrase)
   - Pattern 4: "search results" (as phrase)

3. **offer** - Matches whole words: "offer", "compensation", "package", "extend", or "congratulations"

4. **noise** - Matches whole words: "unsubscribe", "newsletter", "digest", "promotion", or "marketing"

## Quick Reference: Most Common Patterns

| What You Want | Regex Pattern | JSON Format |
|---------------|---------------|-------------|
| Word "hello" anywhere | `hello` | `"hello"` |
| Multiple word options | `hello\|hi\|hey` | `"hello\|hi\|hey"` |
| Phrase with spaces | `hello\\sworld` | `"hello\\\\sworld"` |
| Whole word only | `\\bhello\\b` | `"\\\\bhello\\\\b"` |
| Email domain | `@example\\.com` | `"@example\\\\.com"` |
| Optional word | `colou?r` | `"colou?r"` |
| One or more spaces | `hello\\s+world` | `"hello\\\\s+world"` |

## Best Practices

1. **Be Specific**: Use word boundaries `\\b` to match whole words only (avoid partial matches)
2. **Multi-Word Phrases**: Use `\\s` for spaces in phrases like `"thank\\syou"`
3. **Test Patterns**: Always test in the Label Rule Debugger (`/debug/label_rule/`) with real messages
4. **Disable Unused Labels**: Set pattern to `"None"` for labels you don't want to match
5. **Remember JSON Escaping**: In JSON, write `\\s` for regex `\s`, and `\\b` for regex `\b`
6. **Keep It Simple**: Use only the regex features you need; simpler patterns are easier to maintain

## Label Rule Debugger
The Label Rule Debugger (`/debug/label_rule/`) allows you to:
- Paste a raw Gmail message
- See which labels matched
- View which specific patterns triggered the match
- See highlighted words/phrases that caused the match
- Verify "No Matches" when no patterns match

## Technical Details

### Regex Engine
- Uses Python's `re` module (standard library)
- All patterns are **case-insensitive** (`re.IGNORECASE` flag)
- Full documentation: https://docs.python.org/3/library/re.html

### In Label Rule Debugger (tracker/views.py)
- Loads patterns from `message_labels` in `patterns.json`
- Compiles each pattern as a standard Python regex
- Applies `re.IGNORECASE` for case-insensitive matching
- Extracts matched text for highlighting
- Shows "No Matches" if no patterns match
- Never shows "None" as a match

### In Parser (parser.py)
- Loads patterns from top-level keys in `patterns.json` (e.g., `"application"`, `"interview"`)
- Compiles patterns as regex with case-insensitive flag
- Used for message classification during ingestion

### Regex Subset Supported
While the full Python regex syntax is available, we recommend using only:
- **Literals**: Plain text (e.g., `hello`)
- **Alternation**: `|` for OR
- **Whitespace**: `\s` for spaces/tabs/newlines
- **Word boundaries**: `\b` for whole word matching
- **Quantifiers**: `*` (zero or more), `+` (one or more), `?` (optional)
- **Grouping**: `()` for grouping alternatives
- **Escaping**: `\.` for literal dot, etc.

**Avoid advanced features** like lookaheads, backreferences, or complex nesting unless you're comfortable debugging regex.

## Common Issues

### Pattern Not Matching
- Check for typos in the pattern
- Ensure escaped spaces `\ ` are used for multi-word phrases
- Verify word boundaries `\b` are correctly placed
- Test in Label Rule Debugger

### Too Many Matches
- Add word boundaries `\b` to be more specific
- Use more precise multi-word phrases
- Split broad patterns into separate label categories

### Pattern Errors
- Ensure regex special characters are properly escaped
- Check for unmatched parentheses or brackets
- Validate JSON syntax in patterns.json
