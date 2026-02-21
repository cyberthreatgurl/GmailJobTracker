from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from tracker.models import Company, CompanyOperatingCity
from tracker.views.companies import _sync_company_operating_cities


class CompaniesInCityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _make_company(self, name, location=""):
        now = timezone.now()
        return Company.objects.create(
            name=name,
            location=location,
            domain=f"{name.lower().replace(' ', '')}.com",
            first_contact=now,
            last_contact=now,
        )

    def test_city_search_matches_hq_location_fuzzy(self):
        company = self._make_company("Company A", location="Dahlgren, Virginia")

        response = self.client.get("/companies_in_city/?city=Dahlgren")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, company.name)

    def test_city_search_matches_additional_operating_city_fuzzy(self):
        company = self._make_company("Company B", location="San Francisco, CA")
        CompanyOperatingCity.objects.create(company=company, city="Dallas, Texas")

        response = self.client.get("/companies_in_city/?city=Dallas")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, company.name)

    def test_sync_operating_cities_creates_and_dedupes(self):
        company = self._make_company("Company C", location="Seattle")

        _sync_company_operating_cities(
            company,
            "Dahlgren, Virginia\nDallas, Texas\ndahlgren, virginia\n\nDallas, Texas",
        )

        cities = list(
            CompanyOperatingCity.objects.filter(company=company)
            .order_by("normalized_city")
            .values_list("city", flat=True)
        )
        self.assertEqual(cities, ["Dahlgren, Virginia", "Dallas, Texas"])

    def test_sync_operating_cities_removes_deleted_entries(self):
        company = self._make_company("Company D", location="Austin")
        CompanyOperatingCity.objects.create(company=company, city="Dahlgren")
        CompanyOperatingCity.objects.create(company=company, city="Dallas")

        _sync_company_operating_cities(company, "Dahlgren")

        cities = list(
            CompanyOperatingCity.objects.filter(company=company)
            .values_list("city", flat=True)
        )
        self.assertEqual(cities, ["Dahlgren"])
