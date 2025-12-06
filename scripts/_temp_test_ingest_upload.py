import sys
from pathlib import Path
sys.path.insert(0, r'C:\Users\kaver\code\GmailJobTracker')
from scripts.ingest_eml import ingest_eml_bytes
p = r'd:\Users\kaver\Downloads\Your Application with ICF.eml'
raw = open(p,'rb').read()
res = ingest_eml_bytes(raw, apply=True, create_tt=True, thread_id_override=None, auto_confirm=True)
print('RESULT:', res)
