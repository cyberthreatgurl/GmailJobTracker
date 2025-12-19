"""Quick test to verify parser.py loads patterns from message_labels structure."""

import os

import django

# Configure Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import parser

print("✅ Parser loaded successfully")
print(f"\nLoaded {len(parser._MSG_LABEL_PATTERNS)} label patterns:")

for label, patterns in parser._MSG_LABEL_PATTERNS.items():
    print(f"  {label}: {len(patterns)} patterns")

print("\nLabel excludes loaded:")
for label, excludes in parser._MSG_LABEL_EXCLUDES.items():
    print(f"  {label}: {len(excludes)} exclude patterns")

print("\nPattern structure check:")
print(f"  PATTERNS has 'message_labels' key: {'message_labels' in parser.PATTERNS}")
if "message_labels" in parser.PATTERNS:
    print(f"  message_labels has {len(parser.PATTERNS['message_labels'])} labels")
