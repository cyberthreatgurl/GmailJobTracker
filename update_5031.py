#!/usr/bin/env python3
"""Update parser.py line 5031 with comprehensive cancelled patterns."""

with open('parser.py', 'r') as f:
    lines = f.readlines()

# Check if line 5030 (0-indexed) is the comment we expect
if lines[5030].strip() == '# Check for cancelled in email text':
    # Replace lines 5031-5033 (old check) with new comprehensive pattern check
    new_code = '''                            # Check for cancelled position indicators in email text
                            combined_text = (metadata.get("subject", "") + " " + metadata.get("body", ""))
                            # Use the same patterns as early_detection cancelled_position
                            cancelled_patterns = [
                                r'\\b(?:decided|chosen)\\s+not\\s+to\\s+(?:move\\s+forward\\s+with\\s+)?fill(?:ing)?\\s+(?:this|the)\\s+(?:role|position)\\b',
                                r'\\bevolving\\s+business\\s+needs\\b.*\\bnot\\s+(?:to\\s+)?(?:move\\s+forward|proceed|fill)\\b',
                                r'\\bnot\\s+(?:to\\s+)?move\\s+forward\\s+with\\s+filling\\s+(?:this|the)\\s+(?:role|position)\\b',
                                r'\\b(?:to\\s+)?close\\s+(?:the|this)\\s+(?:[\\w\\s]+\\s+)?(?:role|position)\\s+and\\s+not\\s+move\\s+forward\\b',
                                r'\\b(?:determined|decided)\\s+to\\s+close\\s+(?:the|this)\\s+(?:role|position)\\b',
                                r'\\b(?:role|position)\\s+(?:has\\s+been\\s+)?(?:closed|cancelled|canceled)\\b',
                                r'\\bnot\\s+(?:to\\s+)?(?:move\\s+forward|proceed)\\s+with\\s+(?:filing|filling)\\s+(?:this|the)\\s+(?:role|position)\\b',
                                r'\\b(?:cancelled|canceled|closed/cancelled|cancelled/closed)\\b',
                            ]
                            if any(re.search(pattern, combined_text, re.IGNORECASE) for pattern in cancelled_patterns):
                                application_obj.cancelled = True
'''
    # Remove old 3 lines (5030-5032: comment + combined_text + if check)
    lines = lines[:5030] + [new_code] + lines[5033:]
    
    with open('parser.py', 'w') as f:
        f.writelines(lines)
    print('✓ Updated parser.py line 5031 with comprehensive cancelled patterns')
    print(f'✓ Replaced {3} lines with {len(new_code.splitlines())} lines')
else:
    print('✗ Line 5031 does not match expected content')
    print(f'Found: {repr(lines[5030])}')
