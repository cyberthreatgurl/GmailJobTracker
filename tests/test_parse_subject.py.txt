import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from parser import parse_subject

test_subjects = [
    "Your Google data is ready to download",
    "Lead Cyber Security Analyst (Hybrid) at CareFirst BlueCross BlueShield",
    "Thank you for applying to Bowhead",
    "Interview Confirmation – SAIC",
    "Application Confirmation – Peraton",
    "New jobs similar to Strategic Engineer at Lenovo",
    "Security Alert: New sign-in from Chrome",
    "Weekly Bulletin – Tech Jobs in DC",
    "UMKC- SSE has an open position",
    "Google Verification Code"
]

for subject in test_subjects:
    result = parse_subject(subject)
    print(f"🔍 Subject: {subject}")
    print(f"🧪 Parsed: {result}\n")
