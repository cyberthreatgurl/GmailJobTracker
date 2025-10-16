# ml_subject_classifier.py

import joblib
import numpy as np
import os
import re
from pathlib import Path
import json

# --- Paths ---
MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")
MESSAGE_MODEL_PATH = os.path.join(MODEL_DIR, "message_classifier.pkl")
MESSAGE_SUBJECT_VECTORIZER_PATH = os.path.join(MODEL_DIR, "subject_vectorizer.pkl")
MESSAGE_BODY_VECTORIZER_PATH = os.path.join(MODEL_DIR, "body_vectorizer.pkl")
MESSAGE_LABEL_ENCODER_PATH = os.path.join(MODEL_DIR, "message_label_encoder.pkl")

COMPANY_MODEL_PATH = os.path.join(MODEL_DIR, "company_classifier.pkl")
COMPANY_VECTORIZER_PATH = os.path.join(MODEL_DIR, "vectorizer.pkl")
COMPANY_LABEL_ENCODER_PATH = os.path.join(MODEL_DIR, "label_encoder.pkl")

# --- Load whichever model is available ---
if os.path.exists(MESSAGE_MODEL_PATH):
    model = joblib.load(MESSAGE_MODEL_PATH)
    subject_vectorizer = joblib.load(MESSAGE_SUBJECT_VECTORIZER_PATH)
    body_vectorizer = joblib.load(MESSAGE_BODY_VECTORIZER_PATH)
    label_encoder = joblib.load(MESSAGE_LABEL_ENCODER_PATH)
    mode = "message"
    print("🤖 Loaded message-level classifier.")
elif os.path.exists(COMPANY_MODEL_PATH):
    model = joblib.load(COMPANY_MODEL_PATH)
    subject_vectorizer = joblib.load(COMPANY_VECTORIZER_PATH)
    body_vectorizer = None  # company mode doesn't use separate body vec
    label_encoder = joblib.load(COMPANY_LABEL_ENCODER_PATH)
    mode = "company"
    print("🤖 Loaded company-level classifier.")
else:
    model = None
    subject_vectorizer = None
    body_vectorizer = None
    label_encoder = None
    mode = None
    print("No classifier found. Predictions will be skipped.")

# Optional aliases
_MODEL = model
_LABEL_ENCODER = label_encoder


def _decode_label(idx: int) -> str:
    """Return a human-readable class label from a predicted index."""
    if model is None:
        return "unknown"
    # If the model exposes class labels directly
    if hasattr(model, "classes_"):
        cls = model.classes_[idx]
        # If already a string, just return it
        if isinstance(cls, str):
            return cls
        # Try to map encoded class back to string via label_encoder
        le = _LABEL_ENCODER
        if le is not None and hasattr(le, "inverse_transform"):
            try:
                return str(le.inverse_transform([cls])[0])
            except Exception:
                pass
        # If label_encoder is a list/sequence and cls is int index
        if (
            isinstance(le, (list, tuple))
            and isinstance(cls, int)
            and 0 <= cls < len(le)
        ):
            return str(le[cls])
        # Fallback
        return str(cls)
    return "unknown"


# Load patterns for rule-based classification
PATTERNS_PATH = Path(__file__).parent / "json" / "patterns.json"


def _load_patterns():
    try:
        with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_PATTERNS = _load_patterns()


def rule_label(subject: str, body: str = "") -> str | None:
    """Apply regex rules before ML prediction."""
    text = f"{subject or ''} {body or ''}".lower()

    # Interview keywords (high priority)
    if re.search(
        r"\b(interview|schedule|screening|availability|calendly|book a time)\b", text
    ):
        return "interview_invite"

    # Application confirmation
    if re.search(
        r"\b(thank you for applying|application (received|submitted)|we received your application)\b",
        text,
    ):
        return "job_application"

    # Rejection
    if re.search(
        r"\b(not selected|won\'?t move forward|decided to move forward with other|regret to inform)\b",
        text,
    ):
        return "rejection"

    # Job alerts/newsletters
    if re.search(
        r"\b(job alert|new jobs? matching|recommended for you|jobs? you might like|unsubscribe)\b",
        text,
    ):
        return "job_alert"

    # Headhunter/recruiter outreach
    if re.search(
        r"\b(recruiting|talent acquisition|opportunity|reach out|would love to connect)\b",
        text,
    ):
        return "head_hunter"

    # Noise
    if re.search(r"\b(newsletter|digest|promotion|marketing|sale)\b", text):
        return "noise"

    return None


def predict_subject_type(subject: str, body: str = "", threshold: float = 0.6):
    # Try rule-based first
    rule_result = rule_label(subject, body)

    # If confident rule match, use it
    if rule_result:
        return {
            "label": rule_result,
            "confidence": 0.95,
            "ignore": rule_result in {"noise", "job_alert"},
            "method": "rules",
        }

    # Fall back to ML model
    if model is None or subject_vectorizer is None or body_vectorizer is None:
        return {"label": "unknown", "confidence": 0.0, "ignore": False}

    # Use separate vectorizers for subject and body
    X_subj = subject_vectorizer.transform([subject or ""])
    X_body = body_vectorizer.transform([body or ""])

    from scipy.sparse import hstack

    X = hstack([X_subj, X_body])

    if X.nnz == 0:
        return {"label": "unknown", "confidence": 0.0, "ignore": False}

    proba = model.predict_proba(X)[0]
    idx = int(np.argmax(proba))
    confidence = float(proba[idx])
    label = _decode_label(idx)

    # If ML is uncertain, try rules again as backup
    if confidence < threshold:
        rule_result = rule_label(subject, body)
        if rule_result:
            return {
                "label": rule_result,
                "confidence": confidence,
                "ignore": rule_result in {"noise", "job_alert"},
                "method": "rules_fallback",
            }

    # Use ML prediction
    ignore_labels = {"noise", "job_alert", "head_hunter"}
    return {
        "label": label,
        "confidence": confidence,
        "ignore": label in ignore_labels,
        "method": "ml",
    }
