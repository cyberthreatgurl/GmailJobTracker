#!/usr/bin/env python3
"""
ATS Detection Heuristics

Auto-detect Applicant Tracking Systems from email headers and body content
instead of maintaining a static list of domains.
"""

import re
from typing import Optional, Dict, Any


# Known ATS URL patterns in email bodies/links
ATS_URL_PATTERNS = [
    # Workday
    r"myworkday(?:jobs)?\.com",
    r"workday\.com/.*career",
    
    # Greenhouse
    r"boards\.greenhouse\.io",
    r"greenhouse\.io/.*applications?",
    
    # Lever
    r"jobs\.lever\.co",
    r"hire\.lever\.co",
    
    # iCIMS
    r"icims\.com",
    r"careers-.*\.icims\.com",
    
    # Taleo
    r"taleo\.net",
    r"taleo(?:recruit)?\.com",
    
    # BrassRing (Kenexa/IBM)
    r"brassring\.com",
    r"kenexa\.com",
    
    # SmartRecruiters
    r"smartrecruiters\.com",
    r"jobs\.smartrecruiters\.com",
    
    # Jobvite
    r"jobvite\.com",
    r"jobs\.jobvite\.com",
    
    # ADP
    r"adp\.com/.*career",
    r"recruiting\.adp\.com",
    
    # SAP SuccessFactors
    r"successfactors\.com",
    r"sap\.com/.*career",
    
    # UKG (formerly Kronos/Ultimate)
    r"saashr\.com",
    r"ukg\.com/.*career",
    r"ultipro\.com",
    
    # Paylocity
    r"paylocity\.com",
    
    # Indeed Apply
    r"indeed\.com/.*apply",
    r"indeedassessments\.com",
    
    # LinkedIn Easy Apply
    r"linkedin\.com/.*application",
    
    # Ashby
    r"jobs\.ashbyhq\.com",
    r"ashbyhq\.com",
    
    # Rippling
    r"rippling\.com/.*career",
    
    # Wellfound (AngelList)
    r"wellfound\.com",
    r"angel\.co/.*jobs",
]

# ATS-specific header patterns
ATS_HEADER_PATTERNS = {
    "X-Mailer": [
        r"workday",
        r"greenhouse",
        r"lever",
        r"icims",
        r"taleo",
        r"smartrecruiters",
        r"jobvite",
        r"successfactors",
    ],
    "List-Unsubscribe": [
        r"workday\.com",
        r"greenhouse\.io",
        r"lever\.co",
        r"icims\.com",
        r"taleo\.net",
    ],
    "X-Campaign-Activity": [
        r"application",
        r"candidate",
        r"recruitment",
    ],
}

# Common ATS email address patterns
ATS_SENDER_PATTERNS = [
    r"no-?reply@.*workday",
    r"no-?reply@.*greenhouse",
    r"no-?reply@.*lever",
    r"no-?reply@.*icims",
    r"no-?reply@.*taleo",
    r"careers?@",
    r"jobs?@",
    r"recruiting@",
    r"talent(?:acquisition)?@",
    r"hr@",
    r"applications?@",
]


def detect_ats_from_headers(headers: Dict[str, str]) -> Optional[str]:
    """
    Detect ATS from email headers.
    
    Args:
        headers: Dictionary of email headers (case-insensitive keys preferred)
    
    Returns:
        ATS name if detected, None otherwise
    """
    headers_lower = {k.lower(): v for k, v in headers.items()}
    
    for header_name, patterns in ATS_HEADER_PATTERNS.items():
        header_value = headers_lower.get(header_name.lower(), "")
        for pattern in patterns:
            if re.search(pattern, header_value, re.IGNORECASE):
                # Extract ATS name from pattern
                ats_name = pattern.replace(r"\.", ".").split(".")[0]
                return ats_name.lower()
    
    # Check X-Mailer specifically
    x_mailer = headers_lower.get("x-mailer", "")
    if x_mailer:
        for ats in ["workday", "greenhouse", "lever", "icims", "taleo", "jobvite"]:
            if ats in x_mailer.lower():
                return ats
    
    return None


def detect_ats_from_body(body: str) -> Optional[str]:
    """
    Detect ATS from email body content (URLs, links).
    
    Args:
        body: Email body text (plain or HTML)
    
    Returns:
        ATS name if detected, None otherwise
    """
    body_lower = body.lower()
    
    # Map patterns to ATS names
    ats_mapping = {
        "workday": ["myworkday", "workday.com"],
        "greenhouse": ["greenhouse.io", "boards.greenhouse"],
        "lever": ["lever.co", "jobs.lever"],
        "icims": ["icims.com"],
        "taleo": ["taleo.net", "taleo.com"],
        "brassring": ["brassring.com"],
        "smartrecruiters": ["smartrecruiters.com"],
        "jobvite": ["jobvite.com"],
        "successfactors": ["successfactors.com"],
        "saashr": ["saashr.com"],
        "indeed": ["indeed.com/apply", "indeedassessments"],
        "ashby": ["ashbyhq.com"],
    }
    
    for ats_name, indicators in ats_mapping.items():
        for indicator in indicators:
            if indicator in body_lower:
                return ats_name
    
    return None


def detect_ats_from_sender(sender: str, sender_domain: str) -> Optional[str]:
    """
    Detect ATS from sender email address.
    
    Args:
        sender: Full sender string (e.g., "Careers <careers@company.com>")
        sender_domain: Just the domain part
    
    Returns:
        ATS name if sender appears to be from an ATS, None otherwise
    """
    sender_lower = sender.lower()
    
    # Check if sender matches ATS patterns
    for pattern in ATS_SENDER_PATTERNS:
        if re.search(pattern, sender_lower, re.IGNORECASE):
            # Check if domain contains ATS name
            for ats in ["workday", "greenhouse", "lever", "icims", "taleo"]:
                if ats in sender_domain.lower():
                    return ats
            # Generic ATS detection (careers@, jobs@, etc.)
            return "generic_ats"
    
    return None


def is_ats_email(headers: Dict[str, str], body: str, sender: str, sender_domain: str) -> Dict[str, Any]:
    """
    Comprehensive ATS detection using all available signals.
    
    Args:
        headers: Email headers dictionary
        body: Email body content
        sender: Full sender string
        sender_domain: Sender domain
    
    Returns:
        Dictionary with:
            - is_ats: bool
            - ats_name: str or None
            - confidence: float (0.0-1.0)
            - detection_source: str
    """
    result = {
        "is_ats": False,
        "ats_name": None,
        "confidence": 0.0,
        "detection_source": None,
    }
    
    # Try header detection (highest confidence)
    ats = detect_ats_from_headers(headers)
    if ats:
        result["is_ats"] = True
        result["ats_name"] = ats
        result["confidence"] = 0.95
        result["detection_source"] = "headers"
        return result
    
    # Try body detection (medium confidence)
    ats = detect_ats_from_body(body)
    if ats:
        result["is_ats"] = True
        result["ats_name"] = ats
        result["confidence"] = 0.85
        result["detection_source"] = "body_urls"
        return result
    
    # Try sender detection (lower confidence)
    ats = detect_ats_from_sender(sender, sender_domain)
    if ats:
        result["is_ats"] = True
        result["ats_name"] = ats
        result["confidence"] = 0.7
        result["detection_source"] = "sender_pattern"
        return result
    
    return result


# For backward compatibility with existing code
def is_ats_domain_heuristic(domain: str, headers: Optional[Dict[str, str]] = None, 
                            body: Optional[str] = None) -> bool:
    """
    Check if a domain is likely an ATS using heuristics.
    
    This can supplement or replace the static ATS_DOMAINS list.
    """
    domain_lower = domain.lower()
    
    # Check URL patterns
    for pattern in ATS_URL_PATTERNS:
        if re.search(pattern, domain_lower, re.IGNORECASE):
            return True
    
    # If headers/body provided, use comprehensive detection
    if headers or body:
        result = is_ats_email(
            headers=headers or {},
            body=body or "",
            sender="",
            sender_domain=domain
        )
        return result["is_ats"]
    
    return False


if __name__ == "__main__":
    # Test the heuristics
    print("ATS Detection Heuristics Test")
    print("=" * 50)
    
    test_domains = [
        "myworkdayjobs.com",
        "saashr.com",
        "greenhouse.io",
        "lever.co",
        "icims.com",
        "taleo.net",
        "example.com",
        "gmail.com",
        "careers.microsoft.com",
    ]
    
    for domain in test_domains:
        is_ats = is_ats_domain_heuristic(domain)
        print(f"  {domain}: {'ATS' if is_ats else 'NOT ATS'}")
    
    print()
    print("Body detection test:")
    test_body = """
    Thank you for applying! Click here to track your application:
    https://company.myworkdayjobs.com/careers/job/12345
    """
    
    result = is_ats_email({}, test_body, "careers@company.com", "company.com")
    print(f"  Detected: {result}")
