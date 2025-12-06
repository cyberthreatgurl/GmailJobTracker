from pathlib import Path
import re
p = Path('tests/email/ARES Opportunities.eml')
text = p.read_text(encoding='utf-8', errors='replace')
# crude plain-text extraction: find the first blank line after headers and take following text
parts = text.split('\n\n', 1)
body = parts[1] if len(parts) > 1 else text
subject = ''
for line in text.splitlines():
    if line.lower().startswith('subject:'):
        subject = line.split(':',1)[1].strip()
        break
sender_domain = ''
for line in text.splitlines():
    if line.lower().startswith('from:'):
        if '@' in line:
            sender_domain = line.split('@')[-1].split()[0].strip().lower()
        break
print('Subject:', subject)
print('Sender domain:', sender_domain)
print('\n--- body preview ---\n', body[:500])
# scheduling regex (same as in parser)
scheduling_rx = re.compile(
    r"(?:please\s+)?(?:let\s+me\s+know\s+when\s+you(?:\s+would|(?:'re|\s+are))?\s+available)|"
    r"available\s+for\s+(?:a\s+)?(?:call|phone\s+call|conversation|interview)|"
    r"would\s+like\s+to\s+discuss\s+(?:the\s+position|this\s+role|the\s+opportunity)|"
    r"schedule\s+(?:a\s+)?(?:call|time|conversation|interview)|"
    r"would\s+you\s+be\s+available",
    re.I | re.DOTALL,
)
print('scheduling_rx.search ->', bool(scheduling_rx.search(subject + ' ' + body)))
print('Full body contains exact phrase "would like to discuss the position" ->', 'would like to discuss the position' in (subject + ' ' + body).lower())
print('Full body contains "please let me know when you would be available" ->', 'please let me know when you would be available' in (subject + ' ' + body).lower())
