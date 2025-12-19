import pathlib
from parser import parse_raw_message, parse_subject


def test_ares_opportunity_parses_as_interview():
    repo_root = pathlib.Path(__file__).parent
    eml_path = repo_root / "emails" / "ARES Opportunities.eml"
    assert eml_path.exists(), f"Missing test fixture: {eml_path}"

    raw = eml_path.read_text(encoding="utf-8", errors="ignore")
    meta = parse_raw_message(raw)

    # parse_subject expects: subject, body, sender, sender_domain
    res = parse_subject(
        meta.get("subject", ""),
        meta.get("body", ""),
        sender=meta.get("sender"),
        sender_domain=meta.get("sender_domain"),
    )

    assert res is not None, "parse_subject returned None"
    assert (
        res.get("label") == "interview_invite"
    ), f"Expected interview_invite, got: {res.get('label')}"
