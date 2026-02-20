#!/usr/bin/env python
"""Test the regex pattern against problematic contracts."""
import re

# Build the state regex pattern (from contract_scraper.py - UPDATED)
_state_re = (
    r"(Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|"
    r"Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|"
    r"Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|"
    r"Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|"
    r"New\s+Hampshire|New\s+Jersey|New\s+Mexico|New\s+York|"
    r"North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|"
    r"Pennsylvania|Rhode\s+Island|South\s+Carolina|South\s+Dakota|"
    r"Tennessee|Texas|Utah|Vermont|Virginia|Virgina|Washington|"
    r"West\s+Virginia|Wisconsin|Wyoming|District\s+of\s+Columbia|D\.C\.|"
    r"Puerto\s+Rico|Guam|U\.S\.\s+Virgin\s+Islands|American\s+Samoa|"
    r"Northern\s+Mariana\s+Islands)"
)

# The regex pattern from contract_scraper.py (UPDATED)
pattern = (
    r"^(?:UPDATE:\s+)?(.+?),\s+"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\-\s]+?),\s+"
    + _state_re
)

# Test cases
test_texts = [
    "Point Blank Protective Apparel & Uniforms, Guánica, Puerto Rico, has been awarded",
    "The Raytheon Co., McKinney, Texas, is being awarded",
    "American Systems Corp., McLean, Virginia, is awarded",
]

for text in test_texts:
    match = re.match(pattern, text)
    if match:
        print(f"✓ MATCH: {text[:60]}")
        print(f"  Company: {match.group(1)}")
        print(f"  City: {match.group(2)}")
        print(f"  State: {match.group(3)}")
    else:
        print(f"✗ NO MATCH: {text[:60]}")
    print()
