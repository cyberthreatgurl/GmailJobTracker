#!/usr/bin/env python3
"""
Pattern Conflict Analysis Script

Analyzes patterns.json for conflicts where multiple patterns match the same text.
Also checks actual database messages for multi-label pattern matches.
"""

import json
import os
import re
import sys
from collections import defaultdict

# Add parent directory for Django imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

import django
django.setup()

from tracker.models import Message


def load_patterns():
    """Load patterns from patterns.json"""
    patterns_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "json",
        "patterns.json"
    )
    with open(patterns_path) as f:
        return json.load(f)


def check_pattern_matches(text, patterns_data):
    """Check which patterns match a given text"""
    matches = []
    
    # Check early detection patterns
    early = patterns_data.get("early_detection", {})
    for label, patterns in early.items():
        for pattern in patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    matches.append(f"early:{label}")
                    break
            except re.error as e:
                print(f"  [REGEX ERROR] {label}: {pattern} - {e}")
    
    # Check message label patterns
    labels = patterns_data.get("message_labels", {})
    for label, patterns in labels.items():
        for pattern in patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    matches.append(f"label:{label}")
                    break
            except re.error as e:
                print(f"  [REGEX ERROR] {label}: {pattern} - {e}")
    
    return matches


def analyze_test_subjects(patterns_data):
    """Test synthetic subjects for pattern conflicts"""
    test_subjects = [
        "Thank you for applying to Software Engineer at Acme Corp",
        "Your application has been received",
        "We regret to inform you",
        "Thank you for your interest in the position",
        "Interview scheduled for Monday",
        "Phone screen with hiring manager",
        "Job opportunity - Senior Developer",
        "Your application status update",
        "Congratulations! Job offer from TechCo",
        "Follow up on your application",
        "New job opportunities this week",
        "Assessment complete for your application",
        "We have reviewed your application",
        "Unfortunately we have decided to move forward",
        "Thanks for your recent application",
        "We appreciate your interest but have decided to pursue other candidates",
        "Schedule your phone screen",
        "Invitation to interview",
        "Your application to Senior Engineer",
        "Application confirmed",
    ]
    
    print("=" * 60)
    print("PATTERN CONFLICT ANALYSIS - TEST SUBJECTS")
    print("=" * 60)
    print()
    
    conflicts_found = 0
    for subject in test_subjects:
        matches = check_pattern_matches(subject, patterns_data)
        
        if len(matches) > 1:
            conflicts_found += 1
            print(f"CONFLICT: \"{subject[:55]}...\"" if len(subject) > 55 else f"CONFLICT: \"{subject}\"")
            print(f"  Matches: {', '.join(matches)}")
            print()
    
    print(f"Total conflicts: {conflicts_found}/{len(test_subjects)} test cases")
    print()
    return conflicts_found


def analyze_database_messages(patterns_data, limit=200):
    """Check actual database messages for pattern conflicts"""
    print("=" * 60)
    print("PATTERN CONFLICT ANALYSIS - DATABASE MESSAGES")
    print("=" * 60)
    print()
    
    # Get messages with their actual labels
    messages = Message.objects.exclude(ml_label="noise").order_by("-timestamp")[:limit]
    
    conflicts = defaultdict(list)
    mislabels = []
    
    for msg in messages:
        subject = msg.subject or ""
        matches = check_pattern_matches(subject, patterns_data)
        
        if len(matches) > 1:
            conflicts[msg.ml_label].append({
                "subject": subject[:60],
                "matches": matches,
                "actual": msg.ml_label,
            })
        
        # Check if actual label matches any pattern
        actual_in_matches = any(
            msg.ml_label in m for m in matches
        )
        if matches and not actual_in_matches and msg.ml_label not in ("other", "noise"):
            mislabels.append({
                "subject": subject[:60],
                "matches": matches,
                "actual": msg.ml_label,
            })
    
    # Report conflicts by label
    total_conflicts = sum(len(v) for v in conflicts.values())
    print(f"Messages with multiple pattern matches: {total_conflicts}/{len(messages)}")
    print()
    
    for label, items in sorted(conflicts.items(), key=lambda x: -len(x[1])):
        print(f"  {label}: {len(items)} conflicts")
        for item in items[:3]:  # Show first 3
            print(f"    - \"{item['subject']}\"")
            print(f"      Patterns: {', '.join(item['matches'])}")
    
    print()
    
    # Report potential mislabels
    if mislabels:
        print(f"Potential mislabels (actual label not in pattern matches): {len(mislabels)}")
        for item in mislabels[:10]:
            print(f"  - \"{item['subject']}\"")
            print(f"    Actual: {item['actual']}, Patterns: {', '.join(item['matches'])}")
        print()
    
    return total_conflicts, len(mislabels)


def find_redundant_patterns(patterns_data):
    """Find patterns that may be redundant (subsets of each other)"""
    print("=" * 60)
    print("REDUNDANT PATTERN ANALYSIS")
    print("=" * 60)
    print()
    
    labels = patterns_data.get("message_labels", {})
    redundant = []
    
    for label, patterns in labels.items():
        for i, p1 in enumerate(patterns):
            for j, p2 in enumerate(patterns):
                if i >= j:
                    continue
                # Check if one pattern is a subset of another (simple heuristic)
                p1_simple = re.sub(r"\\[bBsSwWdD]|\[.*?\]|\(.*?\)", "", p1).lower()
                p2_simple = re.sub(r"\\[bBsSwWdD]|\[.*?\]|\(.*?\)", "", p2).lower()
                
                if p1_simple and p2_simple:
                    if p1_simple in p2_simple or p2_simple in p1_simple:
                        redundant.append({
                            "label": label,
                            "pattern1": p1[:50],
                            "pattern2": p2[:50],
                        })
    
    if redundant:
        print(f"Potentially redundant patterns: {len(redundant)}")
        for item in redundant[:15]:
            print(f"  [{item['label']}]")
            print(f"    1: {item['pattern1']}")
            print(f"    2: {item['pattern2']}")
        print()
    else:
        print("No obvious redundant patterns found.")
        print()
    
    return len(redundant)


def main():
    patterns_data = load_patterns()
    
    # Run all analyses
    test_conflicts = analyze_test_subjects(patterns_data)
    db_conflicts, mislabels = analyze_database_messages(patterns_data)
    redundant = find_redundant_patterns(patterns_data)
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Test subject conflicts: {test_conflicts}")
    print(f"  Database message conflicts: {db_conflicts}")
    print(f"  Potential mislabels: {mislabels}")
    print(f"  Redundant patterns: {redundant}")
    print()


if __name__ == "__main__":
    main()
