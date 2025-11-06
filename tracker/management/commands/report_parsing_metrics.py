from collections import Counter

from django.core.management.base import BaseCommand

from tracker.models import Message, ThreadTracking


class Command(BaseCommand):
    help = "Report metrics on company parsing and ML label assignment"

    def handle(self, *args, **options):
        total_msgs = Message.objects.count()
        total_apps = ThreadTracking.objects.count()
        print(f"Total Messages: {total_msgs}")
        print(f"Total Applications: {total_apps}\n")

        # Company resolution stats
        unresolved = Message.objects.filter(company_source="unresolved").count()
        domain_map = Message.objects.filter(company_source="domain_mapping").count()
        subj_parse = Message.objects.filter(company_source="subject_parse").count()
        ml_pred = Message.objects.filter(company_source="ml_prediction").count()
        body_regex = Message.objects.filter(company_source="body_regex").count()
        sender_name = Message.objects.filter(company_source="sender_name_match").count()
        body_at = Message.objects.filter(company_source="body_at_symbol").count()
        manual = Message.objects.filter(company_source__in=["manual_fix", "normalized"]).count()

        print("Company Source Distribution:")
        print(f"  domain_mapping:   {domain_map}")
        print(f"  subject_parse:    {subj_parse}")
        print(f"  ml_prediction:    {ml_pred}")
        print(f"  body_regex:       {body_regex}")
        print(f"  body_at_symbol:   {body_at}")
        print(f"  sender_name_match:{sender_name}")
        print(f"  manual/normalized:{manual}")
        print(f"  unresolved:       {unresolved}")
        print()

        # ML label distribution
        ml_labels = Counter(Message.objects.values_list("ml_label", flat=True))
        print("ML Label Distribution (Message):")
        for label, count in ml_labels.most_common():
            print(f"  {label or '[blank]'}: {count}")
        print()

        # Confidence score distribution
        conf_bins = [0, 0.5, 0.75, 0.85, 0.95, 1.01]
        conf_labels = ["<0.5", "0.5-0.75", "0.75-0.85", "0.85-0.95", ">=0.95"]
        conf_counts = [0] * (len(conf_bins) - 1)
        for conf in Message.objects.exclude(confidence=None).values_list("confidence", flat=True):
            for i in range(len(conf_bins) - 1):
                if conf_bins[i] <= conf < conf_bins[i + 1]:
                    conf_counts[i] += 1
                    break
        print("Confidence Score Distribution:")
        for label, count in zip(conf_labels, conf_counts):
            print(f"  {label}: {count}")
        print()

        # Applications with unresolved company
        unresolved_apps = ThreadTracking.objects.filter(company_source="unresolved").count()
        print(f"Applications with unresolved company: {unresolved_apps}")
        print()

        # Top 10 most common company names in Message
        top_companies = Counter(
            Message.objects.exclude(company=None).values_list("company__name", flat=True)
        ).most_common(10)
        print("Top 10 Companies (by Message count):")
        for name, count in top_companies:
            print(f"  {name}: {count}")
        print()

        print("Done.")
