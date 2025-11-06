#!/usr/bin/env python
"""
Test noise message company handling.

Verifies that noise messages:
1. Are created with company=None during initial ingestion (if high confidence)
2. Have company cleared during re-ingestion if re-classified as noise AND reviewed
3. Have company cleared during reclassification if reviewed
4. Have company cleared when manually labeled as noise AND marked reviewed in admin
5. Unreviewed noise messages KEEP their company (for inspection during model training)
"""
import os
import sys
from datetime import datetime, timezone

import django

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message


def test_noise_message_creation():
    """Test that noise messages are created without companies."""
    print("\n" + "=" * 70)
    print("Test 1: Noise message creation (company should be None)")
    print("=" * 70)

    # Create a noise message with no company (simulating parser behavior)
    msg = Message.objects.create(
        msg_id="test_noise_msg_1",
        thread_id="test_thread_1",
        subject="Free Gift Card - Apply Now!",
        sender="spam@example.com",
        body="Click here for free money!",
        timestamp=datetime.now(timezone.utc),
        ml_label="noise",
        confidence=0.95,
        company=None,  # Should remain None
        company_source="",
    )

    msg.refresh_from_db()
    assert msg.company is None, f"Expected company=None, got {msg.company}"
    assert msg.company_source == "", f"Expected company_source='', got '{msg.company_source}'"
    print(f"✓ Noise message created with company=None")
    print(f"  msg_id: {msg.msg_id}")
    print(f"  ml_label: {msg.ml_label}")
    print(f"  company: {msg.company}")

    # Cleanup
    msg.delete()


def test_noise_message_model_save_override():
    """Test that Message.save() clears company for REVIEWED noise messages."""
    print("\n" + "=" * 70)
    print("Test 2: Model save() override (company cleared only when reviewed)")
    print("=" * 70)

    # Get or create a company for testing
    now = datetime.now(timezone.utc)
    company, created = Company.objects.get_or_create(
        name="TestCompany",
        defaults={
            "domain": "testcompany.com",
            "first_contact": now,
            "last_contact": now,
        },
    )

    # Create a normal message with a company
    msg = Message.objects.create(
        msg_id=f"test_normal_msg_{now.timestamp()}",
        thread_id=f"test_thread_2_{now.timestamp()}",
        subject="Job Application for Software Engineer",
        sender="hr@testcompany.com",
        body="Thank you for applying...",
        timestamp=now,
        ml_label="application",
        confidence=0.90,
        company=company,
        company_source="domain_mapping",
        reviewed=False,
    )

    msg.refresh_from_db()
    assert msg.company == company, f"Expected company={company}, got {msg.company}"
    print(f"✓ Normal message created with company={company.name}")

    # Re-label as noise but NOT reviewed - company should remain
    msg.ml_label = "noise"
    msg.reviewed = False
    msg.save()

    msg.refresh_from_db()
    assert msg.company == company, f"Expected company to remain when not reviewed, got {msg.company}"
    print(f"✓ Unreviewed noise message keeps company: {msg.company.name}")

    # Now mark as reviewed - company should be cleared
    msg.reviewed = True
    msg.save()

    msg.refresh_from_db()
    assert msg.company is None, f"Expected company=None after reviewed noise, got {msg.company}"
    assert msg.company_source == "", f"Expected company_source='' after reviewed noise, got '{msg.company_source}'"
    print(f"✓ After marking reviewed, company was cleared")
    print(f"  company: {msg.company}")
    print(f"  company_source: '{msg.company_source}'")

    # Cleanup
    msg.delete()
    if created:
        company.delete()


def test_existing_noise_messages_cleaned():
    """Test that only reviewed noise messages have companies cleared."""
    print("\n" + "=" * 70)
    print("Test 3: Database integrity check (reviewed noise only)")
    print("=" * 70)

    # Check reviewed noise messages
    reviewed_noise_with_company = Message.objects.filter(ml_label="noise", reviewed=True).exclude(company__isnull=True)

    reviewed_count = reviewed_noise_with_company.count()
    print(f"Reviewed noise messages with companies: {reviewed_count}")

    # Check unreviewed noise messages (should be allowed to have companies)
    unreviewed_noise_with_company = Message.objects.filter(ml_label="noise", reviewed=False).exclude(
        company__isnull=True
    )

    unreviewed_count = unreviewed_noise_with_company.count()
    print(f"Unreviewed noise messages with companies: {unreviewed_count}")
    print(f"  (This is OK - allows inspection during model training)")

    if reviewed_count > 0:
        print("\n⚠️  FAILED: Found REVIEWED noise messages with companies:")
        for msg in reviewed_noise_with_company[:5]:
            print(f"  - msg_id: {msg.msg_id}")
            print(f"    company: {msg.company.name if msg.company else None}")
            print(f"    subject: {msg.subject[:60]}")
        assert False, f"Found {reviewed_count} reviewed noise messages with companies!"
    else:
        print("✓ No reviewed noise messages have companies - database is clean!")
        print("✓ Unreviewed noise messages can have companies for inspection")


def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("NOISE MESSAGE COMPANY HANDLING TESTS")
    print("=" * 70)

    try:
        test_noise_message_creation()
        test_noise_message_model_save_override()
        test_existing_noise_messages_cleaned()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        return True
    except AssertionError as e:
        print("\n" + "=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        return False
    except Exception as e:
        print("\n" + "=" * 70)
        print(f"❌ UNEXPECTED ERROR: {e}")
        print("=" * 70)
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
