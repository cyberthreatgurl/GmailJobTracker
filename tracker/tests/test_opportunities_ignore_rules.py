from django.contrib.auth.models import User
from django.test import Client, TestCase

from tracker.models import ContractIgnoreRule, SamGovOpportunity
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