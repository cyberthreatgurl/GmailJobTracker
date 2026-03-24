from django.contrib.auth.models import User
from django.test import Client, TestCase

from tracker.models import ContractIgnoreRule, SamGovOpportunity


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