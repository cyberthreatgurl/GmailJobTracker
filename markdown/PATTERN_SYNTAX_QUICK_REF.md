# Pattern Syntax Quick Reference

## Standard: Python Regular Expressions (Regex)

GmailJobTracker uses **standard Python regex** with **case-insensitive** matching.

## Essential Syntax (What You Need)

### 1. Literal Text
Just type the text you want to match:
```json
"hello"
```
Matches: "hello", "Hello", "HELLO" (case-insensitive)

### 2. OR (Alternation) with |
Match any of several alternatives:
```json
"cat|dog|bird"
```
Matches: "cat" OR "dog" OR "bird"

### 3. Spaces with \s
Match whitespace (space, tab, newline):
```json
"hello\\sworld"
```
**In JSON, write `\\s` (double backslash)**
Matches: "hello world", "hello  world"

### 4. Word Boundaries with \b  
Match whole words only:
```json
"\\bhello\\b"
```
**In JSON, write `\\b` (double backslash)**
Matches: "hello world", "say hello"
Doesn't match: "hellothere", "othello"

### 5. Special Characters
Escape special characters with backslash:
```json
"example\\.com"
```
**In JSON, write `\\.` for literal dot**
Matches: "example.com" (literal dot, not any character)

## JSON Escaping (CRITICAL)

In JSON files, backslashes are escaped (doubled):

| Regex | In JSON | What It Matches |
|-------|---------|-----------------|
| `\s` | `"\\s"` | Space/tab/newline |
| `\b` | `"\\b"` | Word boundary |
| `\.` | `"\\."` | Literal dot |

## Real-World Examples

### Example 1: Referral Emails
```json
"referral": ["referral|referred|recommend\\syou|\\bintro\\b|connect\\syou\\swith"]
```
Matches:
- "referral" or "referred"
- "recommend you" (with space)
- "intro" (whole word)
- "connect you with" (with spaces)

### Example 2: Job Alerts
```json
"job_alert": ["job\\salert|job\\salerts|careercenter@computer\\.org"]
```
Matches:
- "job alert" or "job alerts" (with space)
- "careercenter@computer.org" (literal dot)

### Example 3: Rejection Emails
```json
"rejection": ["we\\sregret|not\\smoving\\sforward|position\\sclosed"]
```
Matches:
- "we regret" (with space)
- "not moving forward" (with spaces)
- "position closed" (with space)

### Example 4: Whole Words Only
```json
"offer": ["\\b(offer|compensation|package)\\b"]
```
Matches: "offer", "compensation", "package" (whole words only)
Doesn't match: "offered", "packages", "repackage"

## Pattern Testing

Test your patterns at: `/debug/label_rule/`
1. Paste a Gmail message
2. See which patterns matched
3. View highlighted matches

## Common Mistakes

❌ **Wrong:** `"hello world"` - Matches "hello world" but also "helloXworld"
✅ **Right:** `"hello\\sworld"` - Matches only with space

❌ **Wrong:** `"intro"` - Matches "introduction", "introspection"  
✅ **Right:** `"\\bintro\\b"` - Matches only "intro" as whole word

❌ **Wrong:** `"example.com"` - Dot matches any character
✅ **Right:** `"example\\.com"` - Matches literal dot

❌ **Wrong:** `"\s"` in JSON - Single backslash
✅ **Right:** `"\\s"` in JSON - Double backslash

## Need More?

Full Python regex documentation: https://docs.python.org/3/library/re.html

But for 95% of use cases, you only need:
- Plain text
- `|` for OR
- `\\s` for spaces
- `\\b` for word boundaries
- `\\.` for literal dots
