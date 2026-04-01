"""Train the message-type classifier used by GmailJobTracker."""

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, cast

import django
import joblib
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_sample_weight

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from db import load_training_data

MODEL_DIR = "model"
os.makedirs(MODEL_DIR, exist_ok=True)

PATTERNS_PATH = Path(__file__).parent / "json" / "patterns.json"
MIN_SAMPLES_PER_CLASS = 10
MIN_SAMPLES_FOR_STRATIFY = 2
MIN_TOTAL_SAMPLES = 10


def _load_patterns():
    """Load patterns.json content for weak labeling and config."""
    try:
        with open(PATTERNS_PATH, "r", encoding="utf-8") as patterns_file:
            return json.load(patterns_file)
    except Exception:
        return {}


_PATTERNS = _load_patterns()
_WEAK_LABEL_PATTERN_KEYS = {
    "interview_invite": "interview",
    "job_application": "application",
    "rejection": "rejection",
    "offer": "offer",
    "noise": "noise",
}
_MSG_LABEL_PATTERNS = {
    label: [
        re.compile(pattern, re.I)
        for pattern in (_PATTERNS.get("message_labels", {}).get(pattern_key, []))
    ]
    for label, pattern_key in _WEAK_LABEL_PATTERN_KEYS.items()
}


def normalize_training_label(label: Any) -> str:
    """Normalize labels to the app's canonical training taxonomy."""
    normalized = str(label or "").strip().lower()
    return "noise" if normalized == "spam" else normalized


def weak_label(row: Any) -> Any:
    """Assign a heuristic label using regex rules when human labels are absent."""
    text = f"{row.get('subject', '')} {row.get('body', '')}".lower()
    for label in ("interview_invite", "job_application", "rejection", "offer", "noise"):
        for pattern in _MSG_LABEL_PATTERNS.get(label, []):
            if pattern.search(text):
                return label
    return None


def _coerce_extra_training_data(extra_training_data: Any) -> pd.DataFrame:
    """Normalize optional training rows into a dataframe."""
    columns = ["subject", "body", "label"]
    if extra_training_data is None:
        return pd.DataFrame(columns=columns)

    if isinstance(extra_training_data, pd.DataFrame):
        extra_df = extra_training_data.copy()
    else:
        extra_df = pd.DataFrame(list(cast(Iterable[dict], extra_training_data)))

    for column in columns:
        if column not in extra_df.columns:
            extra_df[column] = ""

    extra_df = extra_df[columns].copy()
    extra_df["subject"] = extra_df["subject"].fillna("").astype(str)
    extra_df["body"] = extra_df["body"].fillna("").astype(str)
    extra_df["label"] = extra_df["label"].apply(normalize_training_label)
    extra_df = extra_df[extra_df["label"] != ""]
    return extra_df


def _load_csv_training_data(csv_path: str, csv_label: str, log) -> pd.DataFrame:
    """Load optional CSV training data from disk using an explicit label."""
    if not csv_path:
        return pd.DataFrame(columns=["subject", "body", "label"])

    try:
        csv_df = pd.read_csv(csv_path)
    except Exception as exc:
        raise ValueError(f"Could not load CSV training data from {csv_path}: {exc}") from exc

    if csv_df.empty:
        raise ValueError(f"CSV training file is empty: {csv_path}")

    if "subject" not in csv_df.columns and "body" not in csv_df.columns:
        raise ValueError(
            f"CSV training file must include a 'subject' or 'body' column: {csv_path}"
        )

    csv_df = csv_df.copy()
    if "subject" not in csv_df.columns:
        csv_df["subject"] = ""
    if "body" not in csv_df.columns:
        csv_df["body"] = ""
    csv_df["label"] = normalize_training_label(csv_label)

    log(
        f"[Info] Added {len(csv_df)} CSV training samples from {csv_path} "
        f"as '{csv_df['label'].iloc[0]}'."
    )
    return csv_df[["subject", "body", "label"]]


def _persist_training_metrics(
    y_filtered: pd.Series,
    report_dict: dict,
    report_text: str,
    log,
):
    """Persist training metrics for dashboard reporting."""
    try:
        from tracker.models import ModelTrainingLabelMetric, ModelTrainingRun

        n_samples = int(len(y_filtered))
        n_classes = int(y_filtered.nunique())
        accuracy = float(report_dict.get("accuracy", 0.0))
        macro = report_dict.get("macro avg", {})
        weighted = report_dict.get("weighted avg", {})

        run = ModelTrainingRun.objects.create(
            n_samples=n_samples,
            n_classes=n_classes,
            accuracy=accuracy,
            macro_precision=float(macro.get("precision") or 0.0),
            macro_recall=float(macro.get("recall") or 0.0),
            macro_f1=float(macro.get("f1-score") or 0.0),
            weighted_precision=float(weighted.get("precision") or 0.0),
            weighted_recall=float(weighted.get("recall") or 0.0),
            weighted_f1=float(weighted.get("f1-score") or 0.0),
            label_distribution=json.dumps(y_filtered.value_counts().to_dict(), indent=2),
            classification_report=report_text,
        )

        for label, stats in report_dict.items():
            if label in {"accuracy", "macro avg", "weighted avg"}:
                continue
            if not isinstance(stats, dict):
                continue
            ModelTrainingLabelMetric.objects.create(
                run=run,
                label=str(label),
                precision=float(stats.get("precision") or 0.0),
                recall=float(stats.get("recall") or 0.0),
                f1=float(stats.get("f1-score") or 0.0),
                support=int(stats.get("support") or 0),
            )
        log("[OK] Saved training metrics to DB.")
    except Exception as exc:
        log(f"[Warn] Could not persist training metrics to DB: {exc}")


def _build_model_info(subject_vec, body_vec, y_filtered: pd.Series) -> dict[str, Any]:
    """Build model metadata for the metrics page."""
    all_features = (
        subject_vec.get_feature_names_out().tolist()
        + body_vec.get_feature_names_out().tolist()
    )

    def is_meaningful_feature(feature: str) -> bool:
        if re.match(r"^[0-9a-f]+$", feature):
            return False
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
        if len(feature) <= 2:
            return False
        return bool(re.search(r"[a-z]{3,}", feature.lower()))

    meaningful_features = [
        feature for feature in all_features if is_meaningful_feature(feature)
    ][:100]
    return {
        "trained_on": datetime.now().isoformat(),
        "labels": sorted(y_filtered.unique().tolist()),
        "num_samples": len(y_filtered),
        "total_features": len(all_features),
        "meaningful_features_sample": sorted(meaningful_features),
    }


def train_message_classifier(
    extra_training_data: Any = None,
    verbose: bool = False,
    persist_metrics: bool = True,
    csv_training_path: str | None = None,
    csv_training_label: str | None = None,
) -> dict[str, Any]:
    """Train the classifier using reviewed DB data plus optional imported rows."""
    output_lines: list[str] = []

    def log(message: str):
        output_lines.append(message)

    log(f"[OK] Training started at {datetime.now().isoformat()}")

    base_df = load_training_data()
    extra_df = _coerce_extra_training_data(extra_training_data)
    csv_df = pd.DataFrame(columns=["subject", "body", "label"])
    if csv_training_path:
        if not csv_training_label:
            raise ValueError("CSV training imports require a selected label.")
        csv_df = _load_csv_training_data(csv_training_path, csv_training_label, log)

    frames = [frame for frame in (base_df, csv_df, extra_df) if not frame.empty]
    if frames:
        df = pd.concat(frames, ignore_index=True)
    else:
        df = pd.DataFrame(columns=["subject", "body", "label"])

    if not extra_df.empty:
        log(f"[Info] Added {len(extra_df)} imported training samples.")

    if "body" in df.columns:
        before = len(df)
        df = df[df["body"].fillna("").str.strip() != ""]
        after = len(df)
        if before != after:
            log(f"[Info] Filtered out {before - after} messages with blank/whitespace-only bodies.")

    if "label" in df.columns:
        df["label"] = df["label"].apply(normalize_training_label)
        label_counts = df["label"].value_counts()
        rare_labels = label_counts[label_counts < MIN_SAMPLES_PER_CLASS].index.tolist()
        if rare_labels:
            log(f"[Info] Merging rare classes {rare_labels} into 'other'.")
            df["label"] = df["label"].apply(
                lambda value: "other" if value in rare_labels else value
            )

    if df.empty or "label" not in df.columns or df["label"].isna().all():
        log("[Warning] No human message labels; bootstrapping with regex rules")
        y = df.apply(weak_label, axis=1)
        df = df[y.notna()].copy()
        y = y[y.notna()]
    else:
        y = df["label"].str.lower().str.strip()
        log(f"[OK] Training on {len(y)} human-labeled messages")
        if verbose:
            log(f"Label distribution:\n{y.value_counts()}")

    if df.empty:
        raise SystemExit("[Error] No training data available")

    subject_series = df["subject"] if "subject" in df.columns else pd.Series("", index=df.index)
    body_series = df["body"] if "body" in df.columns else pd.Series("", index=df.index)
    df["text"] = (
        subject_series.fillna("").astype(str) + " " + body_series.fillna("").astype(str)
    ).str.strip()

    class_counts = y.value_counts()
    valid_classes = class_counts[class_counts >= MIN_SAMPLES_FOR_STRATIFY].index
    df_filtered = df[y.isin(valid_classes)].copy()
    y_filtered = y[y.isin(valid_classes)]

    if len(y_filtered) < MIN_TOTAL_SAMPLES:
        raise SystemExit(
            f"[Error] Need at least {MIN_TOTAL_SAMPLES} samples; only have {len(y_filtered)}"
        )

    log(
        f"Training with {len(y_filtered)} samples across {y_filtered.nunique()} classes"
    )

    x_subject = df_filtered["subject"].fillna("")
    x_body = df_filtered["body"].fillna("")

    subject_vec = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        max_df=0.9,
        min_df=1,
        max_features=10000,
    )
    body_vec = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        max_df=0.9,
        min_df=2,
        max_features=40000,
    )

    x_subject_vec = subject_vec.fit_transform(x_subject)
    x_body_vec = body_vec.fit_transform(x_body)
    x_vectors = hstack([x_subject_vec, x_body_vec])

    x_train, x_test, y_train, y_test = train_test_split(
        x_vectors,
        y_filtered,
        test_size=0.2,
        stratify=y_filtered,
        random_state=42,
    )

    sample_weights = compute_sample_weight("balanced", y_train)
    classifier = LogisticRegression(
        solver="lbfgs",
        max_iter=2000,
        C=10.0,
        class_weight="balanced",
    )
    classifier.fit(x_train, y_train)

    y_pred = classifier.predict(x_test)
    report_text = classification_report(y_test, y_pred, zero_division=0)
    report_dict = cast(
        Dict[str, Any],
        classification_report(y_test, y_pred, zero_division=0, output_dict=True),
    )
    log(report_text)

    if verbose:
        try:
            val_pred_counts = pd.Series(y_pred).value_counts().sort_values(ascending=False)
            log(f"[Info] Validation predicted label distribution:\n{val_pred_counts}")
        except Exception:
            pass
        try:
            sample_weight_df = pd.DataFrame(
                {"label": pd.Series(y_train).reset_index(drop=True), "weight": sample_weights}
            )
            effective_weights = (
                sample_weight_df.groupby("label")["weight"].sum().sort_values(ascending=False)
            )
            log(
                "[Info] Effective training class weights (sum of sample weights):\n"
                f"{effective_weights}"
            )
        except Exception:
            pass

    joblib.dump(classifier, "model/message_classifier.pkl")
    joblib.dump(sorted(y_filtered.unique().tolist()), "model/message_label_encoder.pkl")
    joblib.dump(subject_vec, "model/subject_vectorizer.pkl")
    joblib.dump(body_vec, "model/body_vectorizer.pkl")

    model_info = _build_model_info(subject_vec, body_vec, y_filtered)
    with open("model/model_info.json", "w", encoding="utf-8") as info_file:
        json.dump(model_info, info_file, indent=2)

    log("Message-level model artifacts saved to /model/")
    log(f"Model trained on {len(y_filtered)} samples with {y_filtered.nunique()} labels")

    if persist_metrics:
        _persist_training_metrics(y_filtered, report_dict, report_text, log)

    return {
        "output": "\n".join(output_lines),
        "n_samples": int(len(y_filtered)),
        "n_classes": int(y_filtered.nunique()),
        "label_distribution": y_filtered.value_counts().to_dict(),
        "report": report_text,
    }


def main() -> int:
    """CLI entrypoint for model training."""
    parser = argparse.ArgumentParser(description="Train message-type classifier")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--csv-path", help="Optional CSV file to import into training")
    parser.add_argument(
        "--csv-label",
        help="Label to apply to every imported CSV row",
    )
    args = parser.parse_args()

    result = train_message_classifier(
        verbose=args.verbose,
        csv_training_path=args.csv_path,
        csv_training_label=args.csv_label,
    )
    print(result["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())