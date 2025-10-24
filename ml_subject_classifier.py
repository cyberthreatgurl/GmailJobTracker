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

# Toggle verbose debug logging with env var: CLASSIFIER_DEBUG=1
DEBUG = os.getenv("CLASSIFIER_DEBUG", "0") in {"1", "true", "True"}


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

# Compile message label patterns from patterns.json to avoid hardcoding
_COMPILED_PATTERNS = {}
if _PATTERNS and "message_labels" in _PATTERNS:
    for label, pattern_list in _PATTERNS["message_labels"].items():
        _COMPILED_PATTERNS[label] = [
            re.compile(p, re.IGNORECASE) for p in pattern_list if p and p != "None"
        ]

# Labels to suppress (map to 'other'), configurable in patterns.json
_SUPPRESS_LABELS = set(_PATTERNS.get("suppress_labels", []))


def rule_label(subject: str, body: str = "") -> str | None:
    """Apply regex rules from patterns.json before ML prediction.

    Priority order is tuned for specificity:
      1) offer
      2) rejected
      3) interview_invite
      4) job_application
      5) referral
      6) job_alert
      7) head_hunter
      8) noise
    """
    text = f"{subject or ''} {body or ''}".lower()

    priority_order = [
        "offer",
        "rejected",
        "interview_invite",
        "job_application",
        "referral",
        "job_alert",
        "head_hunter",
        "noise",
    ]

    for label in priority_order:
        patterns = _COMPILED_PATTERNS.get(label, [])
        for pattern in patterns:
            if pattern.search(text):
                # If label is suppressed, pretend no rule hit so ML or other rules can proceed
                if label in _SUPPRESS_LABELS:
                    return "other"
                return label

    return None


def _get_rule_label_func():
    """Return the canonical rule_label function from parser.py if available.

    Avoid top-level import to prevent circular imports, since parser imports
    predict_subject_type from this module. Fallback to the local implementation
    if importing parser.rule_label fails for any reason.
    """
    try:
        # Local import to avoid circular import at module load time
        from parser import rule_label as parser_rule_label  # type: ignore

        if callable(parser_rule_label):
            return parser_rule_label
    except Exception:
        pass
    # Fallback to local
    return rule_label


def predict_subject_type(subject: str, body: str = "", threshold: float = 0.6):
    """Predict message label from subject+body using rules first, then ML.

    Returns dict: {label, confidence, ignore, method}
    method is one of: rules | rules_fallback | ml | unknown
    """
    # Get ignore labels from patterns.json (configurable instead of hardcoded)
    ignore_labels = set(
        _PATTERNS.get("ignore_labels", ["noise", "job_alert", "head_hunter"])
    )

    # Debug header
    if DEBUG:
        print(f"[DEBUG] predict_subject_type: subject='{(subject or '')[:80]}'")

    # Try rule-based first (use the canonical implementation from parser.py if available)
    rule_fn = _get_rule_label_func()
    rule_result = rule_fn(subject, body)
    if DEBUG:
        print(f"[DEBUG] rules-first returned: {repr(rule_result)}")
    if rule_result:
        if DEBUG:
            print("[DEBUG] Using rules-first result")
        # Apply suppression mapping, if configured
        mapped_label = "other" if rule_result in _SUPPRESS_LABELS else rule_result
        return {
            "label": mapped_label,
            "confidence": 0.95,
            "ignore": mapped_label in ignore_labels,
            "method": "rules" if mapped_label == rule_result else "rules_suppressed",
        }

    if DEBUG:
        print("[DEBUG] No rule match, evaluating ML...")

    # Fall back to ML model
    if model is None or subject_vectorizer is None or body_vectorizer is None:
        if DEBUG:
            print("[DEBUG] ML artifacts missing, returning unknown")
        return {
            "label": "unknown",
            "confidence": 0.0,
            "ignore": False,
            "method": "unknown",
        }

    # Use separate vectorizers for subject and body
    X_subj = subject_vectorizer.transform([subject or ""])  # type: ignore[name-defined]
    X_body = body_vectorizer.transform([body or ""])  # type: ignore[name-defined]

    from scipy.sparse import hstack

    X = hstack([X_subj, X_body])

    if X.nnz == 0:
        print("[DEBUG] Empty feature vector, returning unknown")
        return {
            "label": "unknown",
            "confidence": 0.0,
            "ignore": False,
            "method": "unknown",
        }

    proba = model.predict_proba(X)[0]
    idx = int(np.argmax(proba))
    confidence = float(proba[idx])
    label = _decode_label(idx)
    if DEBUG:
        print(f"[DEBUG] ML predicted: label={label}, confidence={confidence:.3f}")

    # If ML is uncertain, try rules again as backup
    if confidence < threshold:
        rule_result = rule_fn(subject, body)
        if DEBUG:
            print(
                f"[DEBUG] ML below threshold; rules-fallback returned: {repr(rule_result)}"
            )
        if rule_result:
            mapped_label = "other" if rule_result in _SUPPRESS_LABELS else rule_result
            return {
                "label": mapped_label,
                "confidence": confidence,
                "ignore": mapped_label in ignore_labels,
                "method": (
                    "rules_fallback"
                    if mapped_label == rule_result
                    else "rules_fallback_suppressed"
                ),
            }

    # Use ML prediction
    # Suppress ML-only offers or other configured labels
    mapped_label = "other" if label in _SUPPRESS_LABELS else label
    return {
        "label": mapped_label,
        "confidence": confidence,
        "ignore": mapped_label in ignore_labels,
        "method": "ml" if mapped_label == label else "ml_suppressed",
    }
