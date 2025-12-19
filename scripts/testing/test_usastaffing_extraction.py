"""Test usastaffing.gov company extraction from the sample email"""

import re
from bs4 import BeautifulSoup

# Sample email body from the attached message
sample_body = """Dear Adrian Shaw,<br />
<br />
Thank you for your interest in employment with the Department of the Navy.<br />
<br />
This is to inform you that your submitted application for SUPERVISORY IT SPECIALIST (INFOSEC) at the NAVSURFWARCENDLD, in the Department of the Navy has been received.<br />
<br />
To ensure that you receive consideration for this position, read and follow the instructions in the job opportunity announcement.<br />
<br />
We will assess your qualifications based upon your resume, the responses you provided in the questionnaire, as well as all other materials requested in the job opportunity announcement. When this evaluation is completed, you will be notified of the results with another e-mail message.<br />
<br />
If you would like to check the status of this or any other application, log into your USAJOBS account and click on 'Track My Application.'<br />
<br />
PLEASE DO NOT RESPOND TO THIS EMAIL MESSAGE. IT IS AUTOMATICALLY GENERATED."""

sample_subject = "Application for SUPERVISORY IT SPECIALIST (INFOSEC), ST-12829104-26-JLM was Received"

# Extract plain text
body_plain = sample_body
try:
    if body and (
        "<html" in body.lower() or "<style" in body.lower() or "<br" in body.lower()
    ):
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup(["style", "script"]):
            tag.decompose()
        body_plain = soup.get_text(separator=" ", strip=True)
except Exception as e:
    print(f"HTML parsing failed: {e}")
    body_plain = body

print("Plain text body:")
print(body_plain)
print("\n" + "=" * 80 + "\n")

# Test the pattern
usastaffing_pattern = re.search(
    r"at the\s+([A-Z][A-Za-z0-9\s&.,'-]+?),\s+in the Department of",
    body_plain,
    re.IGNORECASE,
)

if usastaffing_pattern:
    extracted = usastaffing_pattern.group(1).strip()
    print(f"✅ MATCH FOUND!")
    print(f"Extracted company: {extracted}")
else:
    print("❌ NO MATCH")

    # Try to debug - show what patterns exist
    print("\nSearching for 'at the' patterns:")
    at_the_matches = re.findall(
        r"at the\s+([A-Za-z0-9\s&.,'-]+)", body_plain, re.IGNORECASE
    )
    for match in at_the_matches:
        print(f"  - {match}")
