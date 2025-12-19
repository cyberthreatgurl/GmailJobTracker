import pytest
from django.utils.timezone import now
from django.db.models import Exists, OuterRef
from datetime import timedelta
from tracker.models import Company, ThreadTracking, Message
from tracker.views import build_sidebar_context


@pytest.mark.django_db
def test_applications_week_distinct_company_count():
    """Ensure Applications This Week counts distinct companies with a true job application in last 7 days.

    Scenario:
    - 6 companies with application threads in range (some threads may share same company -> should not inflate).
    - One older application (>7 days) should not count.
    - A headhunter company should be excluded.
    - Noise thread should be excluded even if dated within range.
    """
    today = now().date()

    # Create 6 distinct companies
    companies = []
    for i in range(6):
        c = Company.objects.create(
            name=f"Company{i}",
            domain=f"company{i}.com",
            status="application",
            first_contact=now(),
            last_contact=now(),
            confidence=0.9,
        )
        companies.append(c)

    # Headhunter company (should be excluded)
    hh = Company.objects.create(
        name="HeadhunterCo",
        domain="headhunter.example",
        status="headhunter",
        first_contact=now(),
        last_contact=now(),
        confidence=0.5,
    )

    # Application messages for the 6 companies within last 7 days
    # (ThreadTracking is optional; count is Message-based for reliability)
    for idx, company in enumerate(companies):
        Message.objects.create(
            company=company,
            company_source="test",
            sender="recruiter@example.com",
            subject="Application Submission",
            body="test",
            body_html="<p>test</p>",
            timestamp=now(),
            msg_id=f"m{idx}",
            thread_id=f"t{idx}",
            ml_label="job_application",
            confidence=0.99,
            reviewed=True,
        )
        # Optional: Create ThreadTracking (not required for count)
        ThreadTracking.objects.create(
            thread_id=f"t{idx}",
            company_source="test",
            company=company,
            job_title="Engineer",
            job_id="J123",
            status="application",
            sent_date=today,
            ml_label="job_application",
        )

    # Older application (>7 days) should not count
    old_company = Company.objects.create(
        name="OldCo",
        domain="oldco.com",
        status="application",
        first_contact=now(),
        last_contact=now(),
        confidence=0.7,
    )
    # Message timestamp is what matters for the count (not ThreadTracking.sent_date)
    Message.objects.create(
        company=old_company,
        company_source="test",
        sender="recruiter@example.com",
        subject="Old Application",
        body="body",
        body_html="<p>old</p>",
        timestamp=now() - timedelta(days=10),  # 10 days ago
        msg_id="m-old",
        thread_id="old-t1",
        ml_label="job_application",
        confidence=0.95,
        reviewed=True,
    )

    # Noise thread inside range should not count
    noise_company = Company.objects.create(
        name="NoiseCo",
        domain="noiseco.com",
        status="application",
        first_contact=now(),
        last_contact=now(),
        confidence=0.3,
    )
    ThreadTracking.objects.create(
        thread_id="noise-t1",
        company_source="test",
        company=noise_company,
        job_title="Engineer",
        job_id="N123",
        status="application",
        sent_date=today,
        ml_label="noise",
    )
    Message.objects.create(
        company=noise_company,
        company_source="test",
        sender="user@example.com",
        subject="Noise Message",
        body="noise",
        body_html="<p>noise</p>",
        timestamp=now(),
        msg_id="m-noise",
        thread_id="noise-t1",
        ml_label="noise",
        confidence=0.10,
        reviewed=True,
    )

    # Headhunter application thread should be excluded
    ThreadTracking.objects.create(
        thread_id="hh-t1",
        company_source="test",
        company=hh,
        job_title="Engineer",
        job_id="H123",
        status="application",
        sent_date=today,
        ml_label="job_application",
    )
    Message.objects.create(
        company=hh,
        company_source="test",
        sender="hh@example.com",
        subject="Headhunter reachout",
        body="headhunter",
        body_html="<p>headhunter</p>",
        timestamp=now(),
        msg_id="m-hh",
        thread_id="hh-t1",
        ml_label="job_application",
        confidence=0.80,
        reviewed=True,
    )

    ctx = build_sidebar_context()

    assert (
        ctx["applications_week"] == 6
    ), f"Expected 6 distinct companies with applications in last 7 days, got {ctx['applications_week']}"
