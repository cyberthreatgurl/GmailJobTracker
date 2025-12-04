import json
import re
from pathlib import Path

P = Path(__file__).resolve().parents[1] / 'json' / 'patterns.json'
with P.open('r', encoding='utf-8') as f:
    data = json.load(f)

subject = 'PERMANENT/ FULL TIME JOB | OT Cyber Security Analyst | Apollo Beach, FL 33572'
body = 'Hi Adrian\nBest Regards,\nAakib Qureshi\nSr Recruitment Executive- IT\nIntegrated Resources, Inc\nWe do offer a referral bonus!'
text = subject + '\n' + body

head_patterns = data['message_labels'].get('head_hunter', [])
ref_patterns = data['message_labels'].get('referral', [])

print('Testing head_hunter patterns:')
for p in head_patterns:
    try:
        rx = re.compile(p, re.I)
    except re.error as e:
        print('  invalid regex:', p, e)
        continue
    if rx.search(text):
        print('  MATCH ->', p)

print('\nTesting referral patterns:')
for p in ref_patterns:
    try:
        rx = re.compile(p, re.I)
    except re.error as e:
        print('  invalid regex:', p, e)
        continue
    if rx.search(text):
        print('  MATCH ->', p)
