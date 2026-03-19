from tracker.views.companies import _extract_locations_from_html

def test_extract_locations_from_structured_html():
    """Test extraction from specific nested div structures, including skipping empty divs."""
    html_content = """
    <div class="location-div">
        <div class="location-element-wrapper">
            <div class="location-block">
                <div class="results-location">Offutt AFB</div>
                <div class="location-comma">,</div>
                <div class="results-location">Nebraska</div>
            </div>
            <div class="location-divider w-condition-invisible">|</div>
            <div class="location-block">
                <div class="results-location w-dyn-bind-empty"></div>
                <div class="location-comma w-condition-invisible">,</div>
                <div class="results-location w-dyn-bind-empty"></div>
            </div>
            <div class="location-block">
                <div class="results-location">Sydney</div>
                <div class="results-location">NSW</div>
                <div class="results-location">Australia</div>
            </div>
        </div>
    </div>
    """
    locations = _extract_locations_from_html(html_content)
    
    assert len(locations) == 2
    assert "Offutt AFB, NE" in locations
    assert "Sydney, NSW, Australia" in locations

def test_extract_locations_from_regex_fallback():
    """Test extraction from unstructured text utilizing the regex fallback."""
    html_content = """
    <html>
        <body>
            <p>Our company is rapidly expanding and hiring in Austin, Texas as well as Seattle, WA.</p>
            <p>We also have international opportunities in Toronto, Ontario, Canada!</p>
            <p>Please note that Peraton Inc, is a great place to work, but not a location.</p>
        </body>
    </html>
    """
    locations = _extract_locations_from_html(html_content)
    
    assert "Austin, TX" in locations
    assert "Seattle, WA" in locations
    assert "Toronto, ON, Canada" in locations
    
    # Ensure the noise filter caught the company name pseudo-location
    assert not any("Inc" in loc for loc in locations)

def test_extract_locations_empty_content():
    """Test edge cases with no parsable locations."""
    assert _extract_locations_from_html("<div>Just some text with no real locations</div>") == []
    assert _extract_locations_from_html("") == []


def test_extract_locations_from_bae_style_search_results_text():
    """BAE search results expose locations as plain text without the Peraton-specific classes."""
    html_content = """
    <div>
        <h3>Principal Cyber Architect Job ID is 120582BR</h3>
        <p>LocationHudson, New Hampshire, United States | CategoryBusiness Development | Job Id120582BR</p>
        <p>LocationFort Meade, Maryland, United States | CategoryIntelligence | Job Id115314BR</p>
        <p>LocationToronto, Ontario, Canada | CategoryEngineering | Job Id999999BR</p>
        <p>Available in 2 locations | CategoryOther Professionals | Job Id111111BR</p>
    </div>
    """

    locations = _extract_locations_from_html(html_content)

    assert "Hudson, NH" in locations
    assert "Fort Meade, MD" in locations
    assert "Toronto, ON, Canada" in locations
    assert not any(loc.lower().startswith("available in") for loc in locations)


def test_extract_locations_uses_library_for_non_hardcoded_region_normalization():
    """Use country_state_city to normalize regions outside the built-in US/Canada maps."""
    html_content = """
    <div>
        <p>LocationSydney, New South Wales, Australia | CategoryEngineering | Job Id200000BR</p>
    </div>
    """

    locations = _extract_locations_from_html(html_content)

    assert "Sydney, NSW, Australia" in locations