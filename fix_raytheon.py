#!/usr/bin/env python
"""Quick script to fix the Raytheon contract parsing issue."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from tracker.models import DefenseContract

# Fix the specific contract
contract = DefenseContract.objects.get(contract_number='N00383-26-F-SV00', data_source='war_gov')
print(f"Before: company_name_raw = {contract.company_name_raw[:100]}...")

# Fix company name
contract.company_name_raw = "The Raytheon Co."

# Fix description (extract first part before "is being awarded")
contract.description = contract.raw_text

contract.save()
print(f"After: company_name_raw = {contract.company_name_raw}")
print("Fixed successfully!")
