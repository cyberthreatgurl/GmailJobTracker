# scratch

from parser import ingest_message

from gmail_auth import get_gmail_service  # or however you initialize it

service = get_gmail_service()

ids = [
    "7A8BC358-6F84-44F2-821A-7B42632D27CB",
    "7E8D369D-6C9D-428D-9395-9FF6ED25A2FD",
    "D91942B1-09E8-45BB-B421-87BB7EA7CD32",
    "1844064055325671059",
]
for msg_id in ids:
    result = ingest_message(service, msg_id)
    print(f"Re-ingestion result: {result}")
