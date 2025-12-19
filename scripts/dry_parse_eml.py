import re
import sys
from pathlib import Path

# Lightweight dry parser: does not import Django or project parser.
# It inspects headers and uses json/companies.json domain mapping.

EML_PATH = r"C:\Users\kaver\OneDrive\Downloads\DHS Cybersecurity Service Application Status Update for the Cybersecurity Research and Development - Leadership position (Vacancy #12404802).eml"
ROOT = Path(r"C:\Users\kaver\code\GmailJobTracker")


def read_eml(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return str(raw)


def extract_headers(text: str):
    headers = {}
    # crude header parse: until first blank line
    parts = text.split("\n\n", 1)
    head = parts[0]
    for line in head.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers


def domain_from_address(addr: str):
    m = re.search(r"@([\w\.-]+)", addr)
    return m.group(1).lower() if m else None


def load_companies_json():
    import json

    p = ROOT / "json" / "companies.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    p = Path(EML_PATH)
    if not p.exists():
        print("EML not found:", EML_PATH)
        return
    text = read_eml(p)
    headers = extract_headers(text)
    subject = headers.get("subject", "")
    sender = headers.get("from", headers.get("sender", ""))
    sender_addr = sender
    domain = domain_from_address(sender_addr) or ""

    print("Subject:", subject)
    print("From:", sender)
    print("Sender domain:", domain)

    cfg = load_companies_json()
    domain_map = cfg.get("domain_to_company", {})
    known = cfg.get("known", [])

    mapped = domain_map.get(domain)
    if mapped:
        print("Domain mapped company:", mapped)
    else:
        # scan known names in the body
        found = None
        for name in known:
            if name.lower() in text.lower():
                found = name
                break
        if found:
            print("Found company name in message body:", found)
        else:
            print("No company mapping or known name found")


if __name__ == "__main__":
    main()
