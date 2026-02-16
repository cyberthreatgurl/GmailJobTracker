#!/usr/bin/env python
"""Test cancelled position patterns against the ARES email."""
import re

text = """Thank you for your interest in the Cybersecurity Program Manager position with ARES. 
At this time, it has been determined to close the Cybersecurity Program Manager position and not move forward with filing this role."""

patterns = [
    r'\b(?:decided|chosen)\s+not\s+to\s+(?:move\s+forward\s+with\s+)?fill(?:ing)?\s+(?:this|the)\s+(?:role|position)\b',
    r'\bevolving\s+business\s+needs\b.*\bnot\s+(?:to\s+)?(?:move\s+forward|proceed|fill)\b',
    r'\bnot\s+(?:to\s+)?move\s+forward\s+with\s+filling\s+(?:this|the)\s+(?:role|position)\b',
    r'\b(?:to\s+)?close\s+(?:the|this)\s+(?:[\w\s]+\s+)?(?:role|position)\s+and\s+not\s+move\s+forward\b',
    r'\b(?:determined|decided)\s+to\s+close\s+(?:the|this)\s+(?:role|position)\b',
    r'\b(?:role|position)\s+(?:has\s+been\s+)?(?:closed|cancelled|canceled)\b',
    r'\bnot\s+(?:to\s+)?(?:move\s+forward|proceed)\s+with\s+(?:filing|filling)\s+(?:this|the)\s+(?:role|position)\b'
]

print("Testing cancelled position detection patterns:")
print(f"Text: {text[:100]}...\n")

matched = False
for i, pattern in enumerate(patterns, 1):
    if re.search(pattern, text, re.IGNORECASE):
        print(f'✓ Pattern {i} MATCHED')
        print(f'  Pattern: {pattern[:80]}...')
        matched = True
        break

if not matched:
    print("✗ No patterns matched")
else:
    print("\n✓ Email would be classified as 'cancelled'")
