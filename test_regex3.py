#!/usr/bin/env python
"""Test the updated regex with startswith check."""
import re

# Build the state regex pattern
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

# Test cases
test_texts = [
    ("The Raytheon Co., McKinney, Texas, is being awarded", "primary"),
    ("The $10,270,400 firm-fixed-price contract (W912HY-26-C-A010) announced on Feb. 3, 2026, to Inland Dredging Company LLC, Dyersburg, Tennessee", "fallback"),
]

for text, expected_pattern in test_texts:
    company_match = None
    pattern_used = None
    
    # Pattern 1 - only if NOT starting with "The $"
    if not text.startswith(("The $", "A $", "An $")):
        company_match = re.match(
            r"^(?:UPDATE:\s+)?(.+?),\s+"
            r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\-\s]+?),?\s+"
            + _state_re,
            text,
        )
        if company_match:
            pattern_used = "primary"
    
    # Pattern 2 - fallback
    if not company_match:
        company_match = re.search(
            r",\s+to\s+([^,]+),\s+"
            r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\-\s]+?),?\s+"
            + _state_re,
            text,
        )
        if company_match:
            pattern_used = "fallback"
    
    if company_match:
        status = "✓" if pattern_used == expected_pattern else "⚠️"
        print(f"{status} {pattern_used.upper()}: {text[:60]}")
        print(f"  Company: {company_match.group(1)}")
        print(f"  City: {company_match.group(2)}")
        print(f"  State: {company_match.group(3)}")
    else:
        print(f"✗ NO MATCH: {text[:60]}")
    print()
