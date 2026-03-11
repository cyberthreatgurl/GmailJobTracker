
import sys
import os
import django
from pathlib import Path
import json
import re

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from parser import EmailBodyParser, RuleClassifier, PATTERNS
# from tracker.utils.email_parsing import EmailBodyParser  # Ensure we use the correct one

def debug_eml_pattern(eml_path, pattern):
    with open(eml_path, 'r', encoding='utf-8') as f:
        raw_eml = f.read()

    # Parse using same logic as ingestion
    print(f"Parsing EML: {eml_path}")
    parsed = EmailBodyParser.parse_raw_eml(raw_eml)
    
    subject = parsed.get('subject', '')
    body = parsed.get('body', '')
    classification_text = parsed.get('classification_text', body)
    
    s = f"{subject or ''} {body or ''}"
    print(f"\nSearching for pattern: {pattern}")
    
    match = re.search(pattern, s, re.IGNORECASE)
    if match:
        print(f"MATCH FOUND: {match.group(0)}")
        print(f"Start: {match.start()}, End: {match.end()}")
        context_start = max(0, match.start() - 50)
        context_end = min(len(s), match.end() + 50)
        print(f"Context: ...{s[context_start:context_end]}...")
    else:
        print("NO MATCH FOUND")
        # Print snippet where we expect it to be
        snippet_words = ["Client", "looking", "Consultant"]
        for word in snippet_words:
            print(f"Word '{word}' found at: {[m.start() for m in re.finditer(word, s, re.IGNORECASE)]}")
            
        # specifically look for "client" and nearby text
        client_matches = list(re.finditer("client", s, re.IGNORECASE))
        if client_matches:
            for m in client_matches:
                start = max(0, m.start() - 50)
                end = min(len(s), m.end() + 50)
                print(f"Near 'client': ...{s[start:end]}...")

if __name__ == "__main__":
    eml_file = "tests/emails/Consultant Industrial Cybersecurity in Virginia.eml"
    pattern = r"(?i)\bour\s+client\s+is\s+looking\s+for\b"
    debug_eml_pattern(eml_file, pattern)
