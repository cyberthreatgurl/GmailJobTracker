# ml_subject_classifier.py

import joblib
import os

# --- Paths ---
MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")
MESSAGE_MODEL_PATH = os.path.join(MODEL_DIR, "message_classifier.pkl")
MESSAGE_VECTORIZER_PATH = os.path.join(MODEL_DIR, "message_vectorizer.pkl")
MESSAGE_LABEL_ENCODER_PATH = os.path.join(MODEL_DIR, "message_label_encoder.pkl")

COMPANY_MODEL_PATH = os.path.join(MODEL_DIR, "company_classifier.pkl")
COMPANY_VECTORIZER_PATH = os.path.join(MODEL_DIR, "vectorizer.pkl")
COMPANY_LABEL_ENCODER_PATH = os.path.join(MODEL_DIR, "label_encoder.pkl")

# --- Load whichever model is available ---
if os.path.exists(MESSAGE_MODEL_PATH):
    model = joblib.load(MESSAGE_MODEL_PATH)
    vectorizer = joblib.load(MESSAGE_VECTORIZER_PATH)
    label_encoder = joblib.load(MESSAGE_LABEL_ENCODER_PATH)
    mode = "message"
    print("🤖 Loaded message-level classifier.")
elif os.path.exists(COMPANY_MODEL_PATH):
    model = joblib.load(COMPANY_MODEL_PATH)
    vectorizer = joblib.load(COMPANY_VECTORIZER_PATH)
    label_encoder = joblib.load(COMPANY_LABEL_ENCODER_PATH)
    mode = "company"
    print("🤖 Loaded company-level classifier.")
else:
    model = None
    vectorizer = None
    label_encoder = None
    mode = None
    print("⚠️ No classifier found. Predictions will be skipped.")

def predict_subject_type(subject, body=""):
    """
    Predict the label for a given subject/body.
    Uses message-level classifier if available, otherwise company-level.
    Returns dict with label, confidence, and ignore flag.
    """
    if not model or not vectorizer or not label_encoder:
        return {"label": "unknown", "confidence": 0.0, "ignore": False}
    
    text = (subject or "") + " " + (body or "")
    X = vectorizer.transform([text])
    pred_encoded = model.predict(X)[0]
    proba = model.predict_proba(X)[0]
    confidence = float(max(proba))
    label = label_encoder.inverse_transform([pred_encoded])[0]

    return {"label": label, "confidence": confidence, "ignore": False}