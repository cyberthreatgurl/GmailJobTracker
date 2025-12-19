import importlib.machinery
import importlib.util
import sys
import re

# Load parser.py as a module by path to avoid import path issues
from pathlib import Path

parser_path = Path(__file__).resolve().parent.parent / "parser.py"
spec = importlib.util.spec_from_file_location("parser_mod", str(parser_path))
parser_mod = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
spec.loader.exec_module(parser_mod)
parse_raw_message = parser_mod.parse_raw_message
rule_label = parser_mod.rule_label
p = "tests/email/ARES Opportunities.eml"
with open(p, "r", encoding="utf-8", errors="replace") as f:
    raw = f.read()
meta = parse_raw_message(raw)
subject = meta.get("subject", "")
body = meta.get("body", "")
sender_domain = meta.get("sender_domain", "")
print("Subject:", subject)
print("Sender domain:", sender_domain)
print("\n--- body preview ---\n", body[:500])
print("\nrule_label ->", rule_label(subject, body, sender_domain))
# scheduling regex (same as in parser)
scheduling_rx = re.compile(
    r"(?:please\s+)?(?:let\s+me\s+know\s+when\s+you(?:\s+would|(?:'re|\s+are))?\s+available)|"
    r"available\s+for\s+(?:a\s+)?(?:call|phone\s+call|conversation|interview)|"
    r"would\s+like\s+to\s+discuss\s+(?:the\s+position|this\s+role|the\s+opportunity)|"
    r"schedule\s+(?:a\s+)?(?:call|time|conversation|interview)|"
    r"would\s+you\s+be\s+available",
    re.I | re.DOTALL,
)
print("scheduling_rx.search ->", bool(scheduling_rx.search(subject + " " + body)))
print(
    'Full body contains exact phrase "would like to discuss the position" ->',
    "would like to discuss the position" in (subject + " " + body).lower(),
)
print(
    'Full body contains "please let me know when you would be available" ->',
    "please let me know when you would be available" in (subject + " " + body).lower(),
)
