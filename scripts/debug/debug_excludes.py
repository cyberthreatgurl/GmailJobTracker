#!/usr/bin/env python
"""Check excludes for interview_invite."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from parser import _MSG_LABEL_EXCLUDES

subject = "Kelly, we have received your application for Engineering Manager, Attack Emulation Team"
body = """Dear Kelly, 

Thank you for applying for the role of Engineering Manager, Attack Emulation Team at Netflix! It's exciting to see your interest in joining the Dream Team and contributing to our mission to entertain the world. Your qualifications and experiences will be reviewed to determine if there's a mutual fit. 

What's next? If there's interest in discussing the position further, you will be contacted about potential next steps. Thank you again for your time and enthusiasm. Expect to hear from us soon. 

Sincerely, 
The Netflix Talent Acquisition Team"""

s = f"{subject} {body}"

print("=== Checking excludes for each label ===")
for label in ("interview_invite", "job_application", "rejected", "offer", "noise"):
    excludes = _MSG_LABEL_EXCLUDES.get(label, [])
    print(f"\n{label}: {len(excludes)} exclude patterns")
    for i, rx in enumerate(excludes):
        match = rx.search(s)
        if match:
            print(f"  ✓ EXCLUDE {i}: {rx.pattern[:80]} → MATCH: '{match.group()}'")
