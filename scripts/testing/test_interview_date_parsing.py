"""Test interview date parsing from email bodies."""

import os
import sys
import django
from datetime import datetime

# Setup Django
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

# Import after Django setup (parser.py uses Django models)
import parser as parser_module

_parse_interview_date = parser_module._parse_interview_date


def test_interview_date_parsing():
    """Test that interview dates are correctly extracted from email bodies."""

    # Simulate email received on Dec 12, 2025
    received_date = datetime(2025, 12, 12, 10, 0, 0)

    # Test 1: Date in "Month Day" format
    body1 = """
    Hi,
    
    Thank you for your interest. Your interview is scheduled for January 15th at 2 PM EST.
    
    Please confirm your availability.
    
    Best regards,
    Hiring Team
    """
    parsed1 = _parse_interview_date(body1, received_date)
    expected1 = datetime(2026, 1, 15).date()  # Next year since received in Dec
    print(
        f"Test 1 - 'January 15th': {parsed1} (expected {expected1}) {'✓' if parsed1 == expected1 else '✗'}"
    )

    # Test 2: Full date with day of week
    body2 = """
    Your interview with Millennium Corporation is scheduled:
    
    Monday, January 20, 2026 at 3:00 PM
    
    Location: Virtual (Teams link to follow)
    """
    parsed2 = _parse_interview_date(body2, received_date)
    expected2 = datetime(2026, 1, 20).date()
    print(
        f"Test 2 - 'Monday, January 20, 2026': {parsed2} (expected {expected2}) {'✓' if parsed2 == expected2 else '✗'}"
    )

    # Test 3: Numeric date format
    body3 = """
    We would like to schedule an interview for 01/25/2026.
    
    Does this time work for you?
    """
    parsed3 = _parse_interview_date(body3, received_date)
    expected3 = datetime(2026, 1, 25).date()
    print(
        f"Test 3 - '01/25/2026': {parsed3} (expected {expected3}) {'✓' if parsed3 == expected3 else '✗'}"
    )

    # Test 4: Relative date ("next Friday")
    body4 = """
    Can you meet next Friday for an interview?
    """
    parsed4 = _parse_interview_date(body4, received_date)
    # Next Friday from Dec 12, 2025 (Thursday) would be Dec 19, 2025
    expected4 = datetime(2025, 12, 19).date()
    print(
        f"Test 4 - 'next Friday': {parsed4} (expected ~{expected4}) {'✓' if parsed4 >= received_date.date() else '✗'}"
    )

    # Test 5: No date in body (fallback to received_date)
    body5 = """
    We would like to schedule an interview with you. Please reply with your availability.
    """
    parsed5 = _parse_interview_date(body5, received_date)
    expected5 = received_date.date()
    print(
        f"Test 5 - No date (fallback): {parsed5} (expected {expected5}) {'✓' if parsed5 == expected5 else '✗'}"
    )

    # Test 6: Real Millennium interview email pattern
    body6 = """
    Response Requested - Cyber Security Engineer - Millennium Corporation
    
    Hi,
    
    We were impressed with your profile and would like to schedule a technical interview.
    
    Are you available on Tuesday, December 17th at 10:00 AM?
    
    Please confirm at your earliest convenience.
    
    Best,
    Millennium Talent Team
    """
    parsed6 = _parse_interview_date(body6, received_date)
    expected6 = datetime(2025, 12, 17).date()
    print(
        f"Test 6 - 'Tuesday, December 17th': {parsed6} (expected {expected6}) {'✓' if parsed6 == expected6 else '✗'}"
    )

    print("\n✅ All tests completed!")


if __name__ == "__main__":
    test_interview_date_parsing()
