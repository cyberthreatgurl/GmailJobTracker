"""Test that interview emails get future interview_date values."""
import os
import sys
import django
from datetime import datetime, timedelta

# Setup Django
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

# Import after Django setup
import parser as parser_module
extract_status_dates = parser_module.extract_status_dates


def test_interview_date_future():
    """Test that interview invites get future dates (7 days ahead)."""
    
    # Simulate email received on Nov 8, 2025
    received_date = datetime(2025, 11, 8, 10, 0, 0)
    
    # Body with interview pattern
    body = """
    Hi,
    
    We would like to schedule an interview with you for the Cyber Security Engineer position.
    
    Please let us know your availability.
    
    Best regards,
    Hiring Team
    """
    
    dates = extract_status_dates(body, received_date)
    interview_date = dates["interview_date"]
    expected_date = (received_date + timedelta(days=7)).date()
    
    print(f"Received date: {received_date.date()}")
    print(f"Interview date: {interview_date}")
    print(f"Expected date: {expected_date}")
    print(f"Is future date? {interview_date > received_date.date()}")
    print(f"Matches expected (7 days ahead)? {interview_date == expected_date}")
    
    if interview_date == expected_date and interview_date > received_date.date():
        print("\n✅ SUCCESS: Interview date correctly set to 7 days in future!")
    else:
        print("\n❌ FAIL: Interview date not set correctly")


if __name__ == "__main__":
    test_interview_date_future()
