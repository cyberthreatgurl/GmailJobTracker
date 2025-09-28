# ml_subject_classifier.py

import joblib
import os

# Load pre-trained model and vectorizer
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'models', 'subject_classifier.pkl')
VECTORIZER_PATH = os.path.join(os.path.dirname(__file__), 'models', 'subject_vectorizer.pkl')

model = joblib.load(MODEL_PATH)
vectorizer = joblib.load(VECTORIZER_PATH)

def predict_subject_type(subject):
    X = vectorizer.transform([subject])
    label = model.predict(X)[0]
    confidence = max(model.predict_proba(X)[0])
    return label, confidence