import os

import django

# Initialize Django before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from scipy.sparse import hstack
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_sample_weight

from db import load_training_data

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
    for k in (
        "interview_invite",
        "job_application",
        "rejected",
        "offer",
        "referral",
        "response" "ghosted",
        "noise",
        "follow-up",
        "ignore",
    )
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
        print(f"[Info] Filtered out {before-after} messages with blank/whitespace-only bodies.")

# --- Merge ultra-rare classes (no upsampling - class weights handle imbalance) ---
MIN_SAMPLES_PER_CLASS = 10
if "label" in df.columns:
    label_counts = df["label"].value_counts()
    rare_labels = label_counts[label_counts < MIN_SAMPLES_PER_CLASS].index.tolist()
    if rare_labels:
        print(f"[Info] Merging rare classes {rare_labels} into 'other'.")
        df["label"] = df["label"].apply(lambda x: "other" if x in rare_labels else x)

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
    if args.verbose:
        print(f"Label distribution:\n{y.value_counts()}")

if df.empty:
    raise SystemExit("[Error] No training data available")

# Combine subject + body
df["text"] = (df.get("subject", "").fillna("") + " " + df.get("body", "").fillna("")).str.strip()

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

subject_vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), max_df=0.9, min_df=2, max_features=10000)
body_vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), max_df=0.9, min_df=2, max_features=40000)

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

# Evaluate on held-out validation split
y_pred = clf.predict(Xte)
print(classification_report(yte, y_pred, zero_division=0))

# Optional, richer diagnostics under --verbose
if args.verbose:
    # Predicted label distribution on validation set (this is the true "after training" view)
    try:
        import pandas as _pd  # lazy import for convenience

        val_pred_counts = _pd.Series(y_pred).value_counts().sort_values(ascending=False)
        print(f"[Info] Validation predicted label distribution:\n{val_pred_counts}")
    except Exception:
        pass

    # Show effective training weights per class (illustrates balancing effect of class weights)
    try:
        import pandas as _pd

        sw_df = _pd.DataFrame({"label": _pd.Series(ytr).reset_index(drop=True), "weight": sample_weights})
        eff_weights = sw_df.groupby("label")["weight"].sum().sort_values(ascending=False)
        print(f"[Info] Effective training class weights (sum of sample weights):\n{eff_weights}")
    except Exception:
        pass

# Capture metrics for persistence
report_text = classification_report(yte, y_pred, zero_division=0)
report_dict = classification_report(yte, y_pred, zero_division=0, output_dict=True)
os.makedirs("model", exist_ok=True)
joblib.dump(clf, "model/message_classifier.pkl")
joblib.dump(sorted(y_filtered.unique().tolist()), "model/message_label_encoder.pkl")
joblib.dump(subject_vec, "model/subject_vectorizer.pkl")
joblib.dump(body_vec, "model/body_vectorizer.pkl")

# Save model info for metrics page
# Filter out HTML/CSS artifacts and keep only meaningful features
all_features = subject_vec.get_feature_names_out().tolist() + body_vec.get_feature_names_out().tolist()


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

# --- Persist training metrics to DB ---
try:
    from tracker.models import (
        ModelTrainingLabelMetric,
        ModelTrainingRun,
    )

    # Aggregate metrics
    n_samples = int(len(y_filtered))
    n_classes = int(y_filtered.nunique())

    # Defensive lookups
    acc = float(report_dict.get("accuracy", 0.0))
    macro = report_dict.get("macro avg", {})
    weighted = report_dict.get("weighted avg", {})

    run = ModelTrainingRun.objects.create(
        n_samples=n_samples,
        n_classes=n_classes,
        accuracy=acc,
        macro_precision=float(macro.get("precision") or 0.0),
        macro_recall=float(macro.get("recall") or 0.0),
        macro_f1=float(macro.get("f1-score") or 0.0),
        weighted_precision=float(weighted.get("precision") or 0.0),
        weighted_recall=float(weighted.get("recall") or 0.0),
        weighted_f1=float(weighted.get("f1-score") or 0.0),
        label_distribution=json.dumps(y_filtered.value_counts().to_dict(), indent=2),
        classification_report=report_text,
    )

    # Per-label metrics
    special_keys = {"accuracy", "macro avg", "weighted avg"}
    for lbl, stats in report_dict.items():
        if lbl in special_keys:
            continue
        # Expect stats to be a dict with precision/recall/f1-score/support
        if not isinstance(stats, dict):
            continue
        ModelTrainingLabelMetric.objects.create(
            run=run,
            label=str(lbl),
            precision=float(stats.get("precision") or 0.0),
            recall=float(stats.get("recall") or 0.0),
            f1=float(stats.get("f1-score") or 0.0),
            support=int(stats.get("support") or 0),
        )
    print("[OK] Saved training metrics to DB.")
except Exception as e:
    print(f"[Warn] Could not persist training metrics to DB: {e}")
