import os
import sys

from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from .models import ATSDomain, Company, CompanyAlias, DomainToCompany, KnownCompany, Message, ThreadTracking
from .utils.companies_io import companies_store


def _should_sync_companies_json() -> bool:
    """Return False for test runs so pytest does not mutate the repo config."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return not any(arg == "test" or arg.endswith("pytest") for arg in sys.argv)


@receiver([post_save, post_delete], sender=KnownCompany)
@receiver([post_save, post_delete], sender=ATSDomain)
@receiver([post_save, post_delete], sender=DomainToCompany)
@receiver([post_save, post_delete], sender=CompanyAlias)
def export_companies(**_kwargs):
    if not _should_sync_companies_json():
        return

    known = list(KnownCompany.objects.values_list("name", flat=True))
    ats_domains = list(ATSDomain.objects.values_list("domain", flat=True))
    domain_to_company = {
        d["domain"]: d["company"]
        for d in DomainToCompany.objects.values("domain", "company")
    }
    aliases = {
        a["alias"]: a["company"]
        for a in CompanyAlias.objects.values("alias", "company")
    }
    companies_store.sync_registry_snapshot(
        known=known,
        ats_domains=ats_domains,
        domain_to_company=domain_to_company,
        aliases=aliases,
        source="signals/export_companies",
    )


@receiver(post_save, sender=Company)
def sync_domain_to_company_on_company_save(instance: Company, **_kwargs):
    """
    When a Company is saved, if it has a valid domain and name, ensure DomainToCompany is upserted.
    This keeps json/companies.json domain_to_company in sync via export_companies signal above.
    """
    name = (instance.name or "").strip()
    domain = (instance.domain or "").strip().lower()
    if not name or not domain:
        return
    # Basic normalization: strip scheme and leading www.
    for prefix in ("http://", "https://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix) :]
    if domain.startswith("www."):
        domain = domain[4:]
    # Only proceed if it looks like a hostname
    if "." not in domain:
        return
    # Upsert mapping
    _, _ = DomainToCompany.objects.update_or_create(
        domain=domain, defaults={"company": name}
    )
    # Trigger export
    export_companies(sender=DomainToCompany)


@receiver(pre_delete, sender=Message)
def cleanup_thread_tracking_before_delete(instance, **_kwargs):
    """
    Before deleting a Message, check if we need to update or delete its ThreadTracking.

    This handles:
    1. If this is the last message in the thread -> delete ThreadTracking
    2. If deleting a rejection message -> clear rejection_date and find next rejection
    3. If deleting an interview message -> clear interview_date and find next interview
    4. Recalculate ml_label based on remaining messages
    """
    thread_id = instance.thread_id

    if not thread_id:
        return

    try:
        thread_tracking = ThreadTracking.objects.get(thread_id=thread_id)
    except ThreadTracking.DoesNotExist:
        return

    # Count remaining messages in this thread (excluding the one being deleted)
    remaining_messages = Message.objects.filter(thread_id=thread_id).exclude(
        msg_id=instance.msg_id
    )
    remaining_count = remaining_messages.count()

    # If this is the last message, delete the ThreadTracking
    if remaining_count == 0:
        print(f"[SIGNAL] Deleting ThreadTracking {thread_id} - last message deleted")
        thread_tracking.delete()
        return

    # Otherwise, update ThreadTracking based on remaining messages
    print(
        f"[SIGNAL] Updating ThreadTracking {thread_id} - "
        f"{remaining_count} messages remain"
    )

    # Recalculate rejection_date
    rejections = remaining_messages.filter(ml_label="rejection").order_by("-timestamp")
    if rejections.exists():
        latest_rejection = rejections.first()
        thread_tracking.rejection_date = latest_rejection.timestamp.date()
    else:
        thread_tracking.rejection_date = None

    # Recalculate interview_date
    interviews = remaining_messages.filter(ml_label="interview_invite").order_by("-timestamp")
    if interviews.exists():
        latest_interview = interviews.first()
        thread_tracking.interview_date = latest_interview.timestamp.date()
    else:
        thread_tracking.interview_date = None

    # Recalculate ml_label - use the most recent message's label
    latest_message = remaining_messages.order_by('-timestamp').first()
    if latest_message:
        thread_tracking.ml_label = latest_message.ml_label
        thread_tracking.ml_confidence = latest_message.confidence

    thread_tracking.save()
    print(
        "[SIGNAL] Updated ThreadTracking: "
        f"rejection_date={thread_tracking.rejection_date}, "
        f"interview_date={thread_tracking.interview_date}, "
        f"ml_label={thread_tracking.ml_label}"
    )
