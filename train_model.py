import os
import django

# Initialize Django before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import re, json, argparse, joblib, pandas as pd
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.calibration import CalibratedClassifierCV
from sklearn.utils.class_weight import compute_sample_weight
from db import load_training_data
from datetime import datetime
from sklearn.pipeline import FeatureUnion
from scipy.sparse import hstack

# --- Config ---
EXPORT_PATH = "labeled_subjects.csv"
MODEL_DIR = "model"
os.makedirs(MODEL_DIR, exist_ok=True)

parser = argparse.ArgumentParser(description="Train message-type classifier")
parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
args = parser.parse_args()

print(f"[OK] Training started at {datetime.now().isoformat()}")

PATTERNS_PATH = Path(__file__).parent / "json" / "patterns.json"


def _load_patterns():
    try:
        with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_PATTERNS = _load_patterns()
_MSG_LABEL_PATTERNS = {
    k: [re.compile(p, re.I) for p in (_PATTERNS.get("message_labels", {}).get(k, []))]
    for k in ("interview_invite", "job_application", "rejected", "offer", "referral","response""ghosted","noise","job_alert","follow-up","ignore")
}


def weak_label(row: pd.Series) -> str | None:
    s = f"{row.get('subject','')} {row.get('body','')}".lower()
    for label in ("interview", "application", "rejection", "offer", "noise"):
        for rx in _MSG_LABEL_PATTERNS.get(label, []):
            if rx.search(s):
                return label
    return None


# Load and prepare data


df = load_training_data()
# Filter out blank/whitespace-only bodies
if "body" in df.columns:
    before = len(df)
    df = df[df["body"].fillna("").str.strip() != ""]
    after = len(df)
    if before != after:
        print(
            f"[Info] Filtered out {before-after} messages with blank/whitespace-only bodies."
        )

# --- Merge ultra-rare classes (no upsampling - class weights handle imbalance) ---
MIN_SAMPLES_PER_CLASS = 10
if "label" in df.columns:
    label_counts = df["label"].value_counts()
    rare_labels = label_counts[label_counts < MIN_SAMPLES_PER_CLASS].index.tolist()
    if rare_labels:
        print(f"[Info] Merging rare classes {rare_labels} into 'other'.")
        df["label"] = df["label"].apply(lambda x: "other" if x in rare_labels else x)

    # Show natural class distribution (no artificial upsampling)
    print(
        f"[Info] Natural class distribution (before training):\n{df['label'].value_counts()}"
    )

if df.empty or "label" not in df.columns or df["label"].isna().all():
    print("[Warning] No human message labels; bootstrapping with regex rules")
    # Apply weak labels as fallback
    y = df.apply(weak_label, axis=1)
    df = df[y.notna()].copy()
    y = y[y.notna()]
else:
    # Use human labels
    y = df["label"].str.lower().str.strip()
    print(f"[OK] Training on {len(y)} human-labeled messages")
    print(f"Label distribution:\n{y.value_counts()}")

if df.empty:
    raise SystemExit("[Error] No training data available")

# Combine subject + body
df["text"] = (
    df.get("subject", "").fillna("") + " " + df.get("body", "").fillna("")
).str.strip()

# Filter out classes with < 2 samples (can't stratify)
min_samples = 2
class_counts = y.value_counts()
valid_classes = class_counts[class_counts >= min_samples].index
df_filtered = df[y.isin(valid_classes)].copy()
y_filtered = y[y.isin(valid_classes)]

if len(y_filtered) < 10:
    raise SystemExit(f"[Error] Need at least 10 samples; only have {len(y_filtered)}")

print(f"Training with {len(y_filtered)} samples across {y_filtered.nunique()} classes")

X_subject = df_filtered["subject"].fillna("")
X_body = df_filtered["body"].fillna("")

subject_vec = TfidfVectorizer(
    lowercase=True, ngram_range=(1, 2), max_df=0.9, min_df=2, max_features=10000
)
body_vec = TfidfVectorizer(
    lowercase=True, ngram_range=(1, 2), max_df=0.9, min_df=2, max_features=40000
)

X_subject_vec = subject_vec.fit_transform(X_subject)
X_body_vec = body_vec.fit_transform(X_body)

Xv = hstack([X_subject_vec, X_body_vec])

Xtr, Xte, ytr, yte = train_test_split(
    Xv,
    y_filtered,
    test_size=0.2,
    stratify=y_filtered,  # ensures balanced split
    random_state=42,
)

sample_weights = compute_sample_weight("balanced", ytr)

base = LogisticRegression(
    solver="lbfgs",
    max_iter=2000,
    C=0.5,
)
clf = CalibratedClassifierCV(base, method="isotonic", cv=3)
clf.fit(Xtr, ytr, sample_weight=sample_weights)  # pass weights here

print(classification_report(yte, clf.predict(Xte), zero_division=0))
os.makedirs("model", exist_ok=True)
joblib.dump(clf, "model/message_classifier.pkl")
joblib.dump(sorted(y_filtered.unique().tolist()), "model/message_label_encoder.pkl")
joblib.dump(subject_vec, "model/subject_vectorizer.pkl")
joblib.dump(body_vec, "model/body_vectorizer.pkl")

# Save model info for metrics page
# Filter out HTML/CSS artifacts and keep only meaningful features
all_features = (
    subject_vec.get_feature_names_out().tolist()
    + body_vec.get_feature_names_out().tolist()
)


def is_meaningful_feature(feature):
    """Filter out HTML/CSS/number artifacts, keep actual words"""
    # Skip if starts with numbers or hex codes
    if re.match(r"^[0-9a-f]+$", feature):
        return False
    # Skip if contains HTML/CSS indicators
    if any(
        keyword in feature.lower()
        for keyword in [
            "div",
            "span",
            "font",
            "px",
            "pt",
            "webkit",
            "mso",
            "margin",
            "padding",
            "border",
            "width",
            "height",
            "display",
            "important",
            "rgba",
            "amp",
            "nbsp",
        ]
    ):
        return False
    # Skip if too short (likely artifacts)
    if len(feature) <= 2:
        return False
    # Keep if contains actual letters and reasonable length
    if re.search(r"[a-z]{3,}", feature.lower()):
        return True
    return False


meaningful_features = [f for f in all_features if is_meaningful_feature(f)][:100]

model_info = {
    "trained_on": datetime.now().isoformat(),
    "labels": sorted(y_filtered.unique().tolist()),
    "num_samples": len(y_filtered),
    "total_features": len(all_features),
    "meaningful_features_sample": sorted(meaningful_features),
}
with open("model/model_info.json", "w") as f:
    json.dump(model_info, f, indent=2)

print("Message-level model artifacts saved to /model/")
print(f"Model trained on {len(y_filtered)} samples with {y_filtered.nunique()} labels")
