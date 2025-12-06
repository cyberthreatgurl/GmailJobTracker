#!/usr/bin/env python3
"""Normalize duplicate Company rows (case-insensitive) and reassign FKs.

Dry-run by default; use --apply to perform changes.

Behavior:
- Finds groups of Company rows where `lower(name)` is identical.
- Chooses a canonical Company per group using this preference order:
  1. A name that exactly matches an entry in `json/companies.json` 'known' list (case-sensitive), if present.
  2. The Company with the most related Messages + ThreadTracking rows.
  3. The first Company in the DB for that name.
- Reassigns `Message.company` and `ThreadTracking.company` to the canonical company and deletes the duplicates.
- Always writes a JSON backup/report under `scripts/normalize_companies_report_<timestamp>.json`.

Usage:
    python scripts/normalize_companies.py --dry-run
    python scripts/normalize_companies.py --apply
    python scripts/normalize_companies.py --apply --preserve "809,922"
"""

import os
import sys
import json
from datetime import datetime

# Setup Django environment
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()

import argparse
from tracker.models import Company, Message, ThreadTracking

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_JSON = os.path.join(ROOT, 'json', 'companies.json')


def load_known_companies():
    try:
        with open(COMPANIES_JSON, 'r', encoding='utf-8') as f:
            j = json.load(f)
            return set(j.get('known', []))
    except Exception:
        return set()


def find_duplicate_groups():
    groups = {}
    for c in Company.objects.all():
        key = c.name.strip().lower()
        groups.setdefault(key, []).append(c)
    # only keep groups with >1 entry
    return {k: v for k, v in groups.items() if len(v) > 1}


def choose_canonical(group, known_set):
    # group: list of Company objs
    # 1) exact match to known_set
    for c in group:
        if c.name in known_set:
            return c
    # 2) pick company with most related messages + threadtracking
    scores = []
    for c in group:
        msg_count = Message.objects.filter(company=c).count()
        tt_count = ThreadTracking.objects.filter(company=c).count()
        scores.append((msg_count + tt_count, msg_count, tt_count, c))
    scores.sort(reverse=True, key=lambda t: (t[0], t[1], t[2]))
    return scores[0][3]


def plan_and_apply(apply=False, preserve_ids=None):
    known = load_known_companies()
    groups = find_duplicate_groups()
    report = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'groups': []
    }

    for key, group in groups.items():
        canonical = choose_canonical(group, known)
        others = [c for c in group if c.id != canonical.id]
        group_report = {
            'key': key,
            'canonical': {'id': canonical.id, 'name': canonical.name},
            'others': [],
        }

        for other in others:
            preserve = str(other.id) in preserve_ids
            msg_count = Message.objects.filter(company=other).count()
            tt_count = ThreadTracking.objects.filter(company=other).count()
            group_report['others'].append({
                'id': other.id,
                'name': other.name,
                'messages': msg_count,
                'threadtracking': tt_count,
                'preserve': preserve,
            })

        report['groups'].append(group_report)

        # Apply changes unless all others are preserved
        if apply:
            for other in others:
                if preserve_ids and str(other.id) in preserve_ids:
                    print(f"Preserving Company id={other.id} name='{other.name}'")
                    continue
                # Reassign Messages and ThreadTracking
                print(f"Reassigning Company id={other.id} -> canonical id={canonical.id}")
                Message.objects.filter(company=other).update(company=canonical)
                ThreadTracking.objects.filter(company=other).update(company=canonical)
                # Delete the other company
                other.delete()

    # write report
    ts = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    out_path = os.path.join(SCRIPT_DIR, f'normalize_companies_report_{ts}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(f"Wrote report to {out_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description='Normalize duplicate Company rows')
    parser.add_argument('--apply', action='store_true', help='Apply changes to DB')
    parser.add_argument('--preserve', help='Comma-separated Company ids to preserve from deletion')

    args = parser.parse_args()
    preserve_ids = set()
    if args.preserve:
        preserve_ids = set([s.strip() for s in args.preserve.split(',') if s.strip()])

    print('Scanning for duplicate company names (case-insensitive)...')
    report = plan_and_apply(apply=args.apply, preserve_ids=preserve_ids)

    # Print summary
    if not report['groups']:
        print('No duplicate company names found.')
    else:
        print('\nDuplicate groups found:')
        for g in report['groups']:
            print(f"- {g['key']}: canonical={g['canonical']['name']} ({g['canonical']['id']})")
            for o in g['others']:
                p = ' (preserved)' if o['preserve'] else ''
                print(f"    - {o['name']} (id={o['id']}) msgs={o['messages']} tt={o['threadtracking']}{p}")

    if not args.apply:
        print('\nDry-run complete. Rerun with --apply to perform the normalization.')


if __name__ == '__main__':
    main()
