import re

tests = [
    "Proofpoint - We have received your application",
    "Northrop Grumman application received",
    "AT&T Application Received",
    "Google application",
]

# Pattern: Match 1-3 capitalized words, stop at " application" or " -"
pattern = r"^([A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|&T?))*?)(?:\s+application|\s+-)"

print("Testing improved pattern:\n")
for test in tests:
    match = re.search(pattern, test, re.IGNORECASE)
    result = match.group(1) if match else "No match"
    print(f"{test}")
    print(f"  → {result}\n")
