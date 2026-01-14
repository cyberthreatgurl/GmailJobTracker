#!/usr/bin/env python
"""Test script to re-ingest the CGI email and verify it uses the existing company.

This script:
1. Reads the CGI email from the EML file
2. Ingests it using parser.ingest_message_from_eml()
3. Verifies that it used company #200 (CGI Inc.) instead of creating company #201 (CGI)
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, Message
from parser import ingest_message_from_eml

def test_cgi_email_ingestion():
    """Test that CGI email uses alias to resolve to CGI Inc."""
    print("=" * 80)
    print("Testing CGI Email Re-Ingestion with Alias Resolution")
    print("=" * 80)
    
    # Read the EML file
    eml_path = "tests/emails/Job Application Acknowledgement - Cyber SME, J1225-1859.eml"
    print(f"\n1. Reading EML file: {eml_path}")
    
    try:
        with open(eml_path, 'r', encoding='utf-8') as f:
            eml_content = f.read()
        print(f"   ✓ File read successfully ({len(eml_content)} bytes)")
    except Exception as e:
        print(f"   ✗ Failed to read file: {e}")
        return False
    
    # Check companies before ingestion
    print(f"\n2. Companies before ingestion:")
    cgi_companies = Company.objects.filter(name__icontains="CGI").order_by("id")
    for company in cgi_companies:
        message_count = company.message_set.count()
        print(f"   - Company #{company.id}: '{company.name}' ({message_count} messages)")
    
    # Ingest the email
    print(f"\n3. Ingesting email...")
    result = ingest_message_from_eml(eml_content, fake_msg_id="test_cgi_email_001")
    print(f"   Result: {result}")
    
    # Check the created/updated message
    print(f"\n4. Checking created/updated message:")
    msg = Message.objects.filter(msg_id="test_cgi_email_001").first()
    if msg:
        print(f"   ✓ Found message: '{msg.subject}'")
        if msg.company:
            print(f"   Company: #{msg.company.id} - '{msg.company.name}'")
            if msg.company.id == 200:
                print(f"   ✓ SUCCESS - Used existing company #200 (CGI Inc.)")
            else:
                print(f"   ✗ FAILED - Used company #{msg.company.id} instead of #200")
                return False
        else:
            print(f"   ✗ No company assigned")
            return False
    else:
        print(f"   ✗ Message not found")
        return False
    
    # Check companies after ingestion
    print(f"\n5. Companies after ingestion:")
    cgi_companies = Company.objects.filter(name__icontains="CGI").order_by("id")
    for company in cgi_companies:
        message_count = company.message_set.count()
        print(f"   - Company #{company.id}: '{company.name}' ({message_count} messages)")
    
    # Verify no new CGI company was created
    cgi_count = cgi_companies.count()
    if cgi_count == 2:
        print(f"\n   ✓ No new CGI company created (still have 2 companies)")
    else:
        print(f"\n   ✗ Unexpected number of CGI companies: {cgi_count}")
    
    print("\n" + "=" * 80)
    print("Test Complete!")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = test_cgi_email_ingestion()
    exit(0 if success else 1)
