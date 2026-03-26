from django.contrib.auth.models import User
from django.test import Client, TestCase

from tracker.models import Company, ContractIgnoreRule, NAICSCode, PSCCode, SamGovOpportunity
from tracker.views.opportunities import _build_opportunity_ui_link


def test_build_opportunity_ui_link_uses_search_url_for_notice_ids():
    url = _build_opportunity_ui_link(
        solicitation_number="W90VN926RA030",
        notice_id="W90VN926RA030",
        api_ui_link="https://sam.gov/opp/W90VN926RA030/view",
    )

    assert url == (
        "https://sam.gov/search/?index=opp&page=1&pageSize=25"
        "&sort=-modifiedDate"
        "&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL"
        "&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bkey%5D=w90vn926ra030"
        "&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D=w90vn926ra030"
        "&sfm%5Bstatus%5D%5Bis_active%5D=true"
            "&sfm%5Bstatus%5D%5Bis_inactive%5D=true"
    )


class OpportunitiesIgnoreRuleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="oppuser", password="testpass")
        self.client.login(username="oppuser", password="testpass")

    def test_opportunities_page_renders_ignore_actions_for_naics_and_psc(self):
        opportunity = SamGovOpportunity.objects.create(
            title="Cyber Ops Support",
            solicitation_number="SOL-001",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541512",
            product_service_code="D318",
        )

        response = self.client.get("/opportunities/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-ignore-rule-type="naics"')
        self.assertContains(response, 'data-ignore-value="541512"')
        self.assertContains(response, 'data-ignore-rule-type="psc"')
        self.assertContains(response, 'data-ignore-value="D318"')
        self.assertContains(response, 'js-ignore-rule')
        self.assertContains(response, 'href="#"')
        self.assertContains(response, opportunity.title)

    def test_opportunities_page_supports_per_column_filters(self):
        matching = SamGovOpportunity.objects.create(
            title="Alpha Cyber Contract",
            solicitation_number="SOL-FILTER-001",
            posted_date="2026-03-20",
            response_date="2026-03-28",
            type="Solicitation",
            department="Department of the Army",
            office="ACC - Aberdeen",
            naics_code="541512",
            product_service_code="D318",
        )
        SamGovOpportunity.objects.create(
            title="Bravo Support Contract",
            solicitation_number="SOL-FILTER-002",
            posted_date="2026-02-12",
            response_date="2026-04-15",
            type="Award Notice",
            department="Department of the Navy",
            office="NAVSEA",
            naics_code="541330",
            product_service_code="R425",
        )

        response = self.client.get(
            "/opportunities/",
            {
                "title": "Alpha",
                "posted_from": "2026-03-01",
                "posted_to": "2026-03-31",
                "response_from": "2026-03-01",
                "response_to": "2026-03-31",
                "type": "Solicitation",
                "department": "Aberdeen",
                "naics": "541512",
                "psc": "D318",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matching.title)
        self.assertNotContains(response, "Bravo Support Contract")

    def test_opportunities_page_supports_sorting_and_renders_column_sort_links(self):
        alpha = SamGovOpportunity.objects.create(
            title="Alpha Opportunity",
            solicitation_number="SOL-SORT-001",
            posted_date="2026-03-20",
            response_date="2026-03-30",
            type="Solicitation",
            department="Army",
            naics_code="541512",
            product_service_code="D318",
        )
        beta = SamGovOpportunity.objects.create(
            title="Beta Opportunity",
            solicitation_number="SOL-SORT-002",
            posted_date="2026-03-21",
            response_date="2026-03-29",
            type="Award Notice",
            department="Navy",
            naics_code="541330",
            product_service_code="R425",
        )

        response = self.client.get("/opportunities/", {"sort": "title", "dir": "asc"})

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertLess(body.index(alpha.title), body.index(beta.title))
        self.assertIn('sort=title', body)
        self.assertIn('sort=posted', body)
        self.assertIn('sort=response', body)
        self.assertIn('sort=type', body)
        self.assertIn('sort=department', body)
        self.assertIn('sort=naics', body)
        self.assertIn('sort=psc', body)

    def test_opportunities_page_renders_lookup_backed_autocomplete_inputs(self):
        NAICSCode.objects.create(code="541512", description="Computer Systems Design Services")
        PSCCode.objects.create(code="D318", description="IT and Telecom - Integrated Hardware")

        response = self.client.get("/opportunities/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'list="naics-options"')
        self.assertContains(response, 'list="psc-options"')
        self.assertContains(response, '<datalist id="naics-options">', html=False)
        self.assertContains(response, '<datalist id="psc-options">', html=False)
        self.assertContains(response, 'value="541512 - Computer Systems Design Services"', html=False)
        self.assertContains(response, 'value="D318 - IT and Telecom - Integrated Hardware"', html=False)

    def test_opportunities_page_accepts_autocomplete_code_description_values(self):
        matching = SamGovOpportunity.objects.create(
            title="Autocomplete Match",
            solicitation_number="SOL-AUTO-001",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541512",
            product_service_code="D318",
        )
        SamGovOpportunity.objects.create(
            title="Autocomplete Other",
            solicitation_number="SOL-AUTO-002",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541330",
            product_service_code="R425",
        )
        NAICSCode.objects.create(code="541512", description="Computer Systems Design Services")
        PSCCode.objects.create(code="D318", description="IT and Telecom - Integrated Hardware")

        response = self.client.get(
            "/opportunities/",
            {
                "naics": "541512 - Computer Systems Design Services",
                "psc": "D318 - IT and Telecom - Integrated Hardware",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matching.title)
        self.assertNotContains(response, "Autocomplete Other")

    def test_opportunities_page_recovers_codes_and_ignore_actions_from_descriptions(self):
        NAICSCode.objects.create(code="541511", description="Custom Computer Programming Services")
        PSCCode.objects.create(
            code="D302",
            description="IT and Telecom - Systems Development",
        )
        opportunity = SamGovOpportunity.objects.create(
            title="Recovered Classification Opportunity",
            solicitation_number="SOL-RECOVERED",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="",
            product_service_code="",
            naics_codes=[
                {"code": "541511", "description": "Custom Computer Programming Services"}
            ],
            raw_response={
                "naicsCodes": [
                    {"code": "541511", "description": "Custom Computer Programming Services"}
                ],
                "classificationCode": "D302",
                "classificationCodeTitle": "IT and Telecom - Systems Development",
            },
        )

        response = self.client.get("/opportunities/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, opportunity.title)
        self.assertContains(response, "541511")
        self.assertContains(response, "Custom Computer Programming Services")
        self.assertContains(response, 'data-ignore-value="541511"')
        self.assertContains(response, "D302")
        self.assertContains(response, "IT and Telecom - Systems Development")
        self.assertContains(response, 'data-ignore-value="D302"')

    def test_opportunities_keyword_search_matches_naics_code(self):
        matching = SamGovOpportunity.objects.create(
            title="Matching NAICS Opportunity",
            solicitation_number="SOL-NAICS-MATCH",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541512",
            product_service_code="D318",
        )
        SamGovOpportunity.objects.create(
            title="Other Opportunity",
            solicitation_number="SOL-OTHER",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541330",
            product_service_code="R425",
        )

        response = self.client.get("/opportunities/", {"q": "541512"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matching.title)
        self.assertNotContains(response, "Other Opportunity")

    def test_opportunities_page_excludes_records_matching_active_naics_or_psc_rules(self):
        hidden_by_naics = SamGovOpportunity.objects.create(
            title="Hidden by NAICS",
            solicitation_number="SOL-NAICS",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541512",
            product_service_code="R499",
        )
        hidden_by_psc = SamGovOpportunity.objects.create(
            title="Hidden by PSC",
            solicitation_number="SOL-PSC",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541519",
            product_service_code="D318",
        )
        visible = SamGovOpportunity.objects.create(
            title="Visible Opportunity",
            solicitation_number="SOL-VISIBLE",
            posted_date="2026-03-20",
            type="Solicitation",
            naics_code="541330",
            product_service_code="R425",
        )

        ContractIgnoreRule.objects.create(rule_type="naics", value=hidden_by_naics.naics_code)
        ContractIgnoreRule.objects.create(rule_type="psc", value=hidden_by_psc.product_service_code)

        response = self.client.get("/opportunities/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, hidden_by_naics.title)
        self.assertNotContains(response, hidden_by_psc.title)
        self.assertContains(response, visible.title)

    def test_opportunities_page_renders_normalized_sam_search_links(self):
        opportunity = SamGovOpportunity.objects.create(
            title="Repair Multiple Failing Fire Hydrants, Camp Carroll",
            solicitation_number="W90VN926RA030",
            posted_date="2026-03-05",
            type="Award Notice",
            ui_link="https://sam.gov/opp/W90VN926RA030/view",
        )

        response = self.client.get("/opportunities/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn(
            "https://sam.gov/search/?index=opp&amp;page=1&amp;pageSize=25"
            "&amp;sort=-modifiedDate"
            "&amp;sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL"
            "&amp;sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bkey%5D=w90vn926ra030"
            "&amp;sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D=w90vn926ra030"
            "&amp;sfm%5Bstatus%5D%5Bis_active%5D=true"
            "&amp;sfm%5Bstatus%5D%5Bis_inactive%5D=true",
            body,
        )
        self.assertNotIn(opportunity.ui_link, body)

    def test_award_notice_shows_awarded_contractor_and_links_matching_company(self):
        company = Company.objects.create(
            name="Acme Federal LLC",
            domain="acmefed.com",
            uei="NWJXD3EE75U7",
            first_contact="2026-03-01T00:00:00Z",
            last_contact="2026-03-01T00:00:00Z",
        )
        SamGovOpportunity.objects.create(
            title="Awarded Cyber Support",
            solicitation_number="AWD-001",
            posted_date="2026-03-20",
            type="Award Notice",
            award={
                "awardeeName": "Acme Federal LLC",
                "awardeeUei": "NWJXD3EE75U7",
            },
        )

        response = self.client.get("/opportunities/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Winning Organization:")
        self.assertContains(response, "Acme Federal LLC")
        self.assertContains(response, "UEI:")
        self.assertContains(response, "NWJXD3EE75U7")
        self.assertContains(response, f'?company={company.id}')

    def test_award_notice_uses_nested_csv_style_awardee_fields(self):
        SamGovOpportunity.objects.create(
            title="CSV Imported Award Notice",
            solicitation_number="CSV-AWD-001",
            posted_date="2026-03-20",
            type="Award Notice",
            raw_response={
                "noticeId": "CSV-AWD-001",
                "raw_response": {
                    "Legal Business Name": "Nested Winner LLC",
                    "Unique Entity ID": "ABCD1234EFGH",
                },
            },
        )

        response = self.client.get("/opportunities/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nested Winner LLC")
        self.assertContains(response, "ABCD1234EFGH")