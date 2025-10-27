import re

subject = "Proofpoint - We have received your application."

patterns = [
    (
        r"application (?:to|for|with)\s+([A-Z][\w\s&\-]+)",
        re.IGNORECASE,
        "application to/for/with",
    ),
    (r"(?:from|with|at)\s+([A-Z][\w\s&\-]+)", re.IGNORECASE, "from/with/at"),
    (r"position\s+@\s+([A-Z][\w\s&\-]+)", re.IGNORECASE, "position @"),
    (
        r"^([A-Z][\w\s&\-]+)\s+(Job|Application|Interview)",
        0,
        "Company Job/Application/Interview",
    ),
    (r"-\s*([A-Z][\w\s&\-]+)\s*-\s*", 0, "dash-Company-dash"),
    (r"^([A-Z][\w\s&\-]+)\s+application", 0, "Company application"),
    (
        r"(?:your application with|application with|interest in|position at)\s+([A-Z][\w\s&\-]+)",
        re.IGNORECASE,
        "application with/interest in/position at",
    ),
    (
        r"update on your ([A-Z][\w\s&\-]+) application",
        re.IGNORECASE,
        "update on your Company",
    ),
    (
        r"thank you for your application with\s+([A-Z][\w\s&\-]+)",
        re.IGNORECASE,
        "thank you for application with",
    ),
    (r"@\s*([A-Z][\w\s&\-]+)", re.IGNORECASE, "@ symbol"),
]

print(f"Testing subject: {subject}\n")

for pattern, flags, name in patterns:
    match = re.search(pattern, subject, flags if flags else 0)
    if match:
        print(f"✓ MATCH: {name}")
        print(f"  Pattern: {pattern}")
        print(f"  Captured: {match.group(1)}")
        print()
