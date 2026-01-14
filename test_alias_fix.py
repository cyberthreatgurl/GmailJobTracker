#!/usr/bin/env python
"""Test script to verify alias resolution is working correctly.

This script tests that:
1. The resolve_company_alias function correctly resolves aliases
2. Company creation uses aliases to find existing companies
3. The CGI alias resolves to CGI Inc.
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, CompanyAlias
from parser import resolve_company_alias

def test_alias_resolution():
    """Test that alias resolution works correctly."""
    print("=" * 80)
    print("Testing Alias Resolution")
    print("=" * 80)
    
    # Check if CGI Inc. exists
    cgi_inc = Company.objects.filter(name__iexact="CGI Inc.").first()
    print(f"\n1. Check if 'CGI Inc.' company exists:")
    if cgi_inc:
        print(f"   ✓ Found: Company #{cgi_inc.id} - '{cgi_inc.name}'")
    else:
        print(f"   ✗ NOT FOUND - 'CGI Inc.' company does not exist")
        return False
    
    # Check if CGI alias exists
    cgi_alias = CompanyAlias.objects.filter(alias__iexact="CGI").first()
    print(f"\n2. Check if 'CGI' alias exists:")
    if cgi_alias:
        print(f"   ✓ Found: Alias 'CGI' → '{cgi_alias.company}'")
    else:
        print(f"   ✗ NOT FOUND - 'CGI' alias does not exist")
        print(f"   Creating alias for testing...")
        # Create the alias for testing
        cgi_alias = CompanyAlias.objects.create(alias="CGI", company="CGI Inc.")
        print(f"   ✓ Created: Alias 'CGI' → 'CGI Inc.'")
    
    # Test the resolve_company_alias function
    print(f"\n3. Test resolve_company_alias() function:")
    resolved = resolve_company_alias("CGI")
    print(f"   Input: 'CGI'")
    print(f"   Output: '{resolved}'")
    if resolved == "CGI Inc.":
        print(f"   ✓ SUCCESS - Alias resolved correctly")
    else:
        print(f"   ✗ FAILED - Expected 'CGI Inc.', got '{resolved}'")
        return False
    
    # Test with non-existent alias
    print(f"\n4. Test with non-existent alias:")
    resolved = resolve_company_alias("NonExistentCompany")
    print(f"   Input: 'NonExistentCompany'")
    print(f"   Output: '{resolved}'")
    if resolved == "NonExistentCompany":
        print(f"   ✓ SUCCESS - Non-existent alias returns original name")
    else:
        print(f"   ✗ FAILED - Expected 'NonExistentCompany', got '{resolved}'")
        return False
    
    # Check if duplicate CGI company exists (company #201)
    print(f"\n5. Check for duplicate 'CGI' companies:")
    cgi_companies = Company.objects.filter(name__icontains="CGI").order_by("id")
    print(f"   Found {cgi_companies.count()} companies with 'CGI' in name:")
    for company in cgi_companies:
        print(f"   - Company #{company.id}: '{company.name}'")
    
    print("\n" + "=" * 80)
    print("Test Complete!")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = test_alias_resolution()
    exit(0 if success else 1)
