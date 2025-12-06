#!/usr/bin/env python
"""Check what's matching in the Netflix email."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import _MSG_LABEL_PATTERNS

subject = "Kelly, we have received your application for Engineering Manager, Attack Emulation Team"
body = """Dear Kelly, 

Thank you for applying for the role of Engineering Manager, Attack Emulation Team at Netflix! It's exciting to see your interest in joining the Dream Team and contributing to our mission to entertain the world. Your qualifications and experiences will be reviewed to determine if there's a mutual fit. 

What's next? If there's interest in discussing the position further, you will be contacted about potential next steps. Thank you again for your time and enthusiasm. Expect to hear from us soon. 

Sincerely, 
The Netflix Talent Acquisition Team"""

s = f"{subject} {body}"

# Check in new order
for label in ("offer", "rejected", "interview_invite", "job_application"):
    patterns = _MSG_LABEL_PATTERNS.get(label, [])
    print(f"\n{label}:")
    for i, rx in enumerate(patterns):
        match = rx.search(s)
        if match:
            context_start = max(0, match.start() - 30)
            context_end = min(len(s), match.end() + 30)
            context = s[context_start:context_end].replace('\n', ' ')
            print(f"  ✓ MATCH: '{match.group()}' in context: ...{context}...")
            print(f"    → Would return '{label}' and stop")
            break
    if not any(rx.search(s) for rx in patterns):
        print(f"  ✗ No matches")
