"""
Test script to demonstrate input validation
Run with: python -m pytest tests/test_validation_demo.py -v
"""

import pytest
from django.core.exceptions import ValidationError
from django.utils.timezone import now
from tracker.models import Company, ThreadTracking
from tracker.forms import ManualEntryForm, CompanyEditForm


class TestCompanyValidation:
    """Test Company model validators"""

    def test_valid_company_name(self):
        """Valid company names should pass"""
        valid_names = [
            "Microsoft Corporation",
            "O'Brien & Associates",
            "Company, Inc.",
            "Test-Company (USA)",
            'Company "Quoted" Name',
        ]
        for name in valid_names:
            company = Company(
                name=name,
                first_contact=now(),
                last_contact=now()
            )
            company.full_clean()  # Should not raise

    def test_invalid_company_name(self):
        """Invalid company names should fail"""
        invalid_names = [
            "Company<script>alert('xss')</script>",
            "Test@Company",
            "Company#Hash",
            "Test|Pipe",
            "Company;Semicolon",
        ]
        for name in invalid_names:
            company = Company(
                name=name,
                first_contact=now(),
                last_contact=now()
            )
            with pytest.raises(ValidationError) as exc_info:
                company.full_clean()
            assert 'name' in exc_info.value.error_dict

    def test_valid_domain(self):
        """Valid domains should pass"""
        valid_domains = [
            "company.com",
            "sub-domain.company.co.uk",
            "test123.domain.org",
        ]
        for domain in valid_domains:
            company = Company(
                name="Test Company",
                domain=domain,
                first_contact=now(),
                last_contact=now()
            )
            company.full_clean()  # Should not raise

    def test_invalid_domain(self):
        """Invalid domains should fail"""
        invalid_domains = [
            "company .com",  # Space
            "company@domain.com",  # @ symbol
            "company/domain",  # Forward slash
        ]
        for domain in invalid_domains:
            company = Company(
                name="Test Company",
                domain=domain,
                first_contact=now(),
                last_contact=now()
            )
            with pytest.raises(ValidationError) as exc_info:
                company.full_clean()
            assert 'domain' in exc_info.value.error_dict

    def test_valid_homepage_url(self):
        """Valid URLs should pass"""
        valid_urls = [
            "https://www.company.com",
            "http://company.com/careers",
            "https://sub.domain.company.org/path",
        ]
        for url in valid_urls:
            company = Company(
                name="Test Company",
                homepage=url,
                first_contact=now(),
                last_contact=now()
            )
            company.full_clean()  # Should not raise

    def test_invalid_homepage_url(self):
        """Invalid URLs should fail"""
        invalid_urls = [
            "ftp://company.com",  # FTP not allowed
            "javascript:alert(1)",  # XSS attempt
            "not a url",  # Invalid format
        ]
        for url in invalid_urls:
            company = Company(
                name="Test Company",
                homepage=url,
                first_contact=now(),
                last_contact=now()
            )
            with pytest.raises(ValidationError) as exc_info:
                company.full_clean()
            assert 'homepage' in exc_info.value.error_dict

    def test_valid_contact_name(self):
        """Valid contact names should pass"""
        valid_names = [
            "John Smith",
            "Mary O'Brien",
            "Dr. Jane Doe, Ph.D.",
            "Jean-Paul",
        ]
        for name in valid_names:
            company = Company(
                name="Test Company",
                contact_name=name,
                first_contact=now(),
                last_contact=now()
            )
            company.full_clean()  # Should not raise

    def test_invalid_contact_name(self):
        """Invalid contact names should fail"""
        invalid_names = [
            "John123",  # No numbers
            "John@Smith",  # No @ symbols
            "John#Smith",  # No hash
        ]
        for name in invalid_names:
            company = Company(
                name="Test Company",
                contact_name=name,
                first_contact=now(),
                last_contact=now()
            )
            with pytest.raises(ValidationError) as exc_info:
                company.full_clean()
            assert 'contact_name' in exc_info.value.error_dict


@pytest.mark.django_db
class TestThreadTrackingValidation:
    """Test ThreadTracking model validators"""

    def test_valid_thread_id(self):
        """Valid thread IDs should pass"""
        from tracker.models import Company
        company = Company.objects.create(
            name="Test Company",
            first_contact=now(),
            last_contact=now()
        )
        valid_ids = [
            "18d4c2f8a1b2c3d4",
            "ABC123XYZ",
            "threadid123",
        ]
        for thread_id in valid_ids:
            tt = ThreadTracking(
                thread_id=thread_id,
                company=company,
                job_title="Test Job",
                status="application",
                sent_date=now().date()
            )
            tt.full_clean()  # Should not raise

    def test_invalid_thread_id(self):
        """Invalid thread IDs should fail"""
        from tracker.models import Company
        company = Company.objects.create(
            name="Test Company",
            first_contact=now(),
            last_contact=now()
        )
        invalid_ids = [
            "18d4c2f8-a1b2",  # No hyphens
            "thread_id_123",  # No underscores
            "thread id",  # No spaces
        ]
        for thread_id in invalid_ids:
            tt = ThreadTracking(
                thread_id=thread_id,
                company=company,
                job_title="Test Job",
                status="application",
                sent_date=now().date()
            )
            with pytest.raises(ValidationError) as exc_info:
                tt.full_clean()
            assert 'thread_id' in exc_info.value.error_dict

    def test_valid_job_title(self):
        """Valid job titles should pass"""
        from tracker.models import Company
        company = Company.objects.create(
            name="Test Company",
            first_contact=now(),
            last_contact=now()
        )
        valid_titles = [
            "Software Engineer II",
            "Director, IT/Cloud Services",
            "Senior DevOps Engineer (Remote)",
            "QA & Testing Lead",
        ]
        for title in valid_titles:
            tt = ThreadTracking(
                thread_id=f"test{valid_titles.index(title)}",
                company=company,
                job_title=title,
                status="application",
                sent_date=now().date()
            )
            tt.full_clean()  # Should not raise

    def test_invalid_job_title(self):
        """Invalid job titles should fail"""
        from tracker.models import Company
        company = Company.objects.create(
            name="Test Company",
            first_contact=now(),
            last_contact=now()
        )
        invalid_titles = [
            "Engineer@Company",  # No @ symbols
            "Developer<script>",  # No HTML tags
            "Job#12345",  # No hash in title
        ]
        for idx, title in enumerate(invalid_titles):
            tt = ThreadTracking(
                thread_id=f"invalid{idx}",
                company=company,
                job_title=title,
                status="application",
                sent_date=now().date()
            )
            with pytest.raises(ValidationError) as exc_info:
                tt.full_clean()
            assert 'job_title' in exc_info.value.error_dict


class TestFormValidation:
    """Test form validators"""

    def test_valid_manual_entry_form(self):
        """Valid form data should pass"""
        data = {
            'entry_type': 'application',
            'company_name': 'Test Company, Inc.',
            'job_title': 'Software Engineer II',
            'job_id': 'JOB-12345',
            'application_date': now().date(),
            'source': 'LinkedIn',
        }
        form = ManualEntryForm(data)
        assert form.is_valid(), form.errors

    def test_invalid_company_name_in_form(self):
        """Invalid company name should fail in form"""
        data = {
            'entry_type': 'application',
            'company_name': 'Company<script>',
            'application_date': now().date(),
        }
        form = ManualEntryForm(data)
        assert not form.is_valid()
        assert 'company_name' in form.errors

    def test_invalid_job_id_in_form(self):
        """Invalid job ID should fail in form"""
        data = {
            'entry_type': 'application',
            'company_name': 'Test Company',
            'job_id': 'JOB#12345',  # Hash not allowed
            'application_date': now().date(),
        }
        form = ManualEntryForm(data)
        assert not form.is_valid()
        assert 'job_id' in form.errors

    def test_valid_company_edit_form(self):
        """Valid company edit form should pass"""
        data = {
            'name': "O'Brien & Associates",
            'domain': 'obrien.com',
            'homepage': 'https://www.obrien.com',
            'career_url': 'https://www.obrien.com/careers',
            'alias': 'OBA',
        }
        form = CompanyEditForm(data)
        assert form.is_valid(), form.errors

    def test_invalid_career_url_in_form(self):
        """Invalid career URL should fail in form"""
        data = {
            'name': 'Test Company',
            'career_url': 'javascript:alert(1)',
        }
        form = CompanyEditForm(data)
        assert not form.is_valid()
        assert 'career_url' in form.errors

    def test_invalid_alias_in_form(self):
        """Invalid alias should fail in form"""
        data = {
            'name': 'Test Company',
            'alias': 'Test@Alias',  # @ not allowed
        }
        form = CompanyEditForm(data)
        assert not form.is_valid()
        assert 'alias' in form.errors


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
