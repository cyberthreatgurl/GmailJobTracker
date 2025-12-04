import importlib.util
from pathlib import Path
import sys

# Load the local parser.py module by path to avoid stdlib conflicts
spec = importlib.util.spec_from_file_location("local_parser", Path(__file__).resolve().parents[1] / "parser.py")
parser = importlib.util.module_from_spec(spec)
sys.modules["local_parser"] = parser
spec.loader.exec_module(parser)

subject = 'PERMANENT/ FULL TIME JOB | OT Cyber Security Analyst | Apollo Beach, FL 33572'
body = 'Best Regards,\nAakib Qureshi\nSr Recruitment Executive- IT\nIntegrated Resources, Inc\nWe do offer a referral bonus!'
print('rule_label ->', parser.rule_label(subject, body))
