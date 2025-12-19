"""Regression test: 'Indeed Application:' subjects must be labeled as job_application.

Ensures rule-based override for Indeed application confirmations beats high-confidence
ML predictions of interview_invite.
"""

from parser import predict_with_fallback, rule_label


def fake_ml_predict(subject, body, sender=""):
    """Simulate an over-confident ML misclassification as interview_invite."""
    return {"label": "interview_invite", "confidence": 0.95}


def test_indeed_application_override():
    subject = "Indeed Application: Senior Systems Security Engineer"
    # Body includes phrases that might trigger interview heuristics like 'discuss the opportunity'
    body = "We'll help you get started. Application submitted. We'd like to discuss the opportunity soon."

    # Sanity: rule_label alone should return job_application
    rl = rule_label(subject, body)
    assert rl == "job_application", f"Expected rule_label job_application, got {rl}"

    result = predict_with_fallback(
        fake_ml_predict, subject, body, sender="indeedapply@indeed.com"
    )
    assert (
        result["label"] == "job_application"
    ), f"Override failed; got {result['label']} (confidence={result.get('confidence')})"
