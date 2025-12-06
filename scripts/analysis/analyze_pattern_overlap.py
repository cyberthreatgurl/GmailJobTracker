#!/usr/bin/env python
"""Analyze pattern overlaps to determine optimal rule order."""

import json

with open("json/patterns.json", "r") as f:
    patterns = json.load(f)

# Test examples of each type
test_cases = {
    "application_confirmation": [
        "Thank you for applying for Software Engineer at Acme Corp",
        "We have received your application for Data Scientist",
        "Your application has been received and will be reviewed",
        "Kelly, we have received your application for Engineering Manager, Attack Emulation Team",
    ],
    "rejection": [
        "We regret to inform you that we have selected another candidate",
        "Unfortunately, we have decided to move forward with other candidates",
        "The position has been closed",
        "We appreciate your interest, but the role is no longer available",
    ],
    "interview": [
        "Please let us know your availability for an interview",
        "We would like to schedule an interview with you",
        "Next steps: Please select a time for your interview",
    ],
    "rejection_after_interview": [
        "Thank you for taking the time to interview. Unfortunately, we have decided to move forward with another candidate",
        "We appreciate your interest and the time spent in interviews, but we regret to inform you the position has been filled",
    ],
}

msg_labels = patterns.get("message_labels", {})

print("=" * 80)
print("PATTERN OVERLAP ANALYSIS")
print("=" * 80)

# Check for overlapping patterns
print("\n1. OVERLAPPING PATTERNS:")
print("-" * 80)

application_patterns = set(msg_labels.get("application", []))
rejection_patterns = set(msg_labels.get("rejection", []))
interview_patterns = set(msg_labels.get("interview", []))

overlap_app_rej = application_patterns & rejection_patterns
overlap_app_int = application_patterns & interview_patterns
overlap_rej_int = rejection_patterns & interview_patterns

if overlap_app_rej:
    print(f"\n⚠️  Application ∩ Rejection: {overlap_app_rej}")
if overlap_app_int:
    print(f"⚠️  Application ∩ Interview: {overlap_app_int}")
if overlap_rej_int:
    print(f"⚠️  Rejection ∩ Interview: {overlap_rej_int}")

# Analyze pattern specificity
print("\n\n2. PATTERN SPECIFICITY ANALYSIS:")
print("-" * 80)


def count_words(pattern):
    """Rough estimate of pattern specificity by word count."""
    return len(pattern.replace("\\s", " ").replace("\\b", "").split())


labels_by_specificity = []
for label in ["application", "rejection", "interview"]:
    pats = msg_labels.get(label, [])
    avg_specificity = sum(count_words(p) for p in pats) / len(pats) if pats else 0
    labels_by_specificity.append((label, avg_specificity, pats))

labels_by_specificity.sort(key=lambda x: x[1], reverse=True)

for label, specificity, patterns in labels_by_specificity:
    print(f"\n{label.upper()}: avg specificity = {specificity:.1f} words")
    print(f"  Most specific: {max(patterns, key=count_words) if patterns else 'N/A'}")
    print(f"  Least specific: {min(patterns, key=count_words) if patterns else 'N/A'}")

# Analyze semantic relationships
print("\n\n3. SEMANTIC RELATIONSHIP:")
print("-" * 80)
print(
    """
Application confirmations:
  - Typically sent IMMEDIATELY after applying
  - Generic, positive tone
  - Patterns: "received", "thank you for applying", "will be reviewed"
  
Interview invites:
  - Sent AFTER application review (days/weeks later)
  - Specific action required (schedule, availability)
  - Patterns: "schedule", "interview", "next steps", "availability"
  
Rejections:
  - Sent AFTER review or interview
  - Negative outcome, definitive closure
  - Patterns: "unfortunately", "other candidates", "not selected", "regret"
  
OVERLAP ISSUE:
  - "received your application" appears in BOTH application and rejection
  - "next steps" can appear in application confirmations ("What's next?")
"""
)

print("\n\n4. RECOMMENDED ORDER:")
print("-" * 80)
print(
    """
MOST SPECIFIC → LEAST SPECIFIC (to avoid false matches):

1. OFFER
   - Most specific: "offer", "compensation", "package", "congratulations"
   - Rarely overlaps with other categories
   
2. REJECTION  
   - Highly specific negative markers: "unfortunately", "other candidates", "not selected"
   - Should be checked BEFORE application to catch "received your application" in rejection context
   - Rejection emails often include "thank you for applying" but add negative outcome
   
3. INTERVIEW
   - Specific action-oriented: "schedule", "availability", "interview"
   - Should be before application to catch "next steps" in interview context
   
4. APPLICATION
   - More generic confirmation language
   - Catch-all for application acknowledgements
   - Should be AFTER rejection/interview to avoid false positives
   
5. RESPONSE/FOLLOW_UP/OTHER
   - Generic catch-alls

RATIONALE:
- Rejection emails often say "we received your application BUT unfortunately..."
- Interview invites might say "next steps" which could match application patterns
- Application confirmations are the most generic/common, so should be last among these three
"""
)

print("\n\n5. CURRENT ORDER vs RECOMMENDED:")
print("-" * 80)
print("CURRENT ORDER:")
print("  1. interview_invite")
print("  2. job_application")
print("  3. rejected")
print("  4. offer")
print("")
print("RECOMMENDED ORDER:")
print("  1. offer              ← Move up (most specific)")
print("  2. rejected           ← Move up (has negative + positive patterns)")
print("  3. interview_invite   ← Keep")
print("  4. job_application    ← Move down (most generic)")
