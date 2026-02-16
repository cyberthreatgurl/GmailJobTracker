#!/usr/bin/env python
"""Test the updated regex pattern against problematic contracts."""
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

# The regex pattern from contract_scraper.py (UPDATED - optional comma after city)
pattern = (
    r"^(?:UPDATE:\s+)?(.+?),\s+"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\-\s]+?),?\s+"  # Optional comma after city
    + _state_re
)

# Test cases
test_texts = [
    "Point Blank Protective Apparel & Uniforms, Guánica, Puerto Rico, has been awarded",
    "The Raytheon Co., McKinney, Texas, is being awarded",
    "American Systems Corp., McLean, Virginia, is awarded",
    "Raytheon, Andover Massachusetts, was awarded",  # No comma between city and state
    "Sabena Aerospace Engineering, Woluwe-Saint-Lambert, Belgium, has been awarded",
    "Atmospheric Environmental Research Inc., a subsidiary of JANUS Research Group LLC, has been awarded a $9,119,149 cost-plus fixed-fee contract",
    "The $10,270,400 firm-fixed-price contract (W912HY-26-C-A010) announced on Feb. 3, 2026, to Inland Dredging Company LLC, Dyersburg, Tennessee",
]

for text in test_texts:
    match = re.match(pattern, text)
    
    # Try fallback if first pattern doesn't match
    if not match:
        fallback_pattern = (
            r",\s+to\s+([^,]+),\s+"
            r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\-\s]+?),?\s+"
            + _state_re
        )
        match = re.search(fallback_pattern, text)
        if match:
            print(f"✓ FALLBACK MATCH: {text[:60]}")
        
    if match:
        if not text.startswith("✓"):  # Not already printed by fallback
            print(f"✓ MATCH: {text[:60]}")
        print(f"  Company: {match.group(1)}")
        print(f"  City: {match.group(2)}")
        print(f"  State: {match.group(3)}")
    else:
        print(f"✗ NO MATCH: {text[:60]}")
    print()
