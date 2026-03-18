"""Regression test for Prudential alias matching."""

from parser import parse_subject, _domain_mapper


def test_prudential_alias_matching():
    """Alias-driven extraction should resolve Prudential from the email body."""
    _domain_mapper.reload_if_needed()

    result = parse_subject(
        subject="Application Submitted for Cybersecurity Engineer",
        body=(
            "Thank you for your interest in the position of Specialist, Cyber Security "
            "(LBPS) at Prudential.\n\nWe have received your application and will review "
            "it carefully."
        ),
        sender="Workday <pru@myworkday.com>",
        sender_domain="myworkday.com",
    )

    assert result.get("company") == "Prudential"
