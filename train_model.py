import os
import joblib
import pandas as pd
from db import load_training_data
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer

# --- Config ---
EXPORT_PATH = "labeled_subjects.csv"
MODEL_DIR = "model"
os.makedirs(MODEL_DIR, exist_ok=True)

# --- Branch 1: If we have manually labeled messages, train on them ---
if os.path.exists(EXPORT_PATH):
    print(f"📂 Found {EXPORT_PATH}, training on manually labeled messages...")
    df = pd.read_csv(EXPORT_PATH)

    # Filter only message rows
    df = df[df["type"] == "message"]

    if df.empty:
        print("⚠️ No labeled messages found in export, falling back to company training.")
        df = None
    else:
        # Prepare text field
        df["text"] = df["subject"].fillna("") + " " + df["body"].fillna("")

        # Encode labels
        le = LabelEncoder()
        df["label_encoded"] = le.fit_transform(df["ml_label"])

        # Filter sparse classes
        label_counts = df["ml_label"].value_counts()
        df = df[df["ml_label"].isin(label_counts[label_counts > 1].index)]

        # Re-encode after filtering
        le = LabelEncoder()
        df["label_encoded"] = le.fit_transform(df["ml_label"])

        print("📊 Label distribution:", df["ml_label"].value_counts())

        # Safety check
        if df["label_encoded"].nunique() < 2:
            print("🚫 Not enough unique labels to train a classifier.")
            exit(0)

        # Vectorize
        vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=5000,
            ngram_range=(1, 2),
        )
        X = vectorizer.fit_transform(df["text"])
        y = df["label_encoded"]

        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Train model
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(X_train, y_train)

        # Evaluate
        y_pred = clf.predict(X_test)
        labels_in_test = sorted(set(y_test))
        target_names = le.inverse_transform(labels_in_test)
        print(classification_report(y_test, y_pred, labels=labels_in_test, target_names=target_names))

        # Save artifacts
        joblib.dump(clf, os.path.join(MODEL_DIR, "message_classifier.pkl"))
        joblib.dump(vectorizer, os.path.join(MODEL_DIR, "message_vectorizer.pkl"))
        joblib.dump(le, os.path.join(MODEL_DIR, "message_label_encoder.pkl"))
        print("✅ Message-level model artifacts saved to /model/")

# --- Branch 2: Otherwise, fall back to company-level training ---
if not os.path.exists(EXPORT_PATH) or df is None or df.empty:
    print("📂 No labeled messages available, training on company data from DB...")
    df = load_training_data()

    print(f"📦 Dataset ready for training: {df.shape[0]} rows")
    print(df.head())

    # Prepare text field
    df["text"] = df["subject"].fillna("") + " " + df["body"].fillna("")

    # Encode labels
    le = LabelEncoder()
    df["company_encoded"] = le.fit_transform(df["company"])

    # Filter sparse classes
    company_counts = df["company"].value_counts()
    df = df[df["company"].isin(company_counts[company_counts > 1].index)]

    # Re-encode after filtering
    le = LabelEncoder()
    df["company_encoded"] = le.fit_transform(df["company"])

    print("📊 Company label distribution:", df["company"].value_counts())

    if df["company_encoded"].nunique() < 2:
        print("🚫 Not enough unique company labels to train a classifier.")
        exit(0)

    # Vectorize
    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=5000,
        ngram_range=(1, 2),
    )
    X = vectorizer.fit_transform(df["text"])
    y = df["company_encoded"]

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Train model
    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    clf.fit(X_train, y_train)

    # Evaluate
    y_pred = clf.predict(X_test)
    labels_in_test = sorted(set(y_test))
    target_names = le.inverse_transform(labels_in_test)
    print(classification_report(y_test, y_pred, labels=labels_in_test, target_names=target_names))

    # Save artifacts
    joblib.dump(clf, os.path.join(MODEL_DIR, "company_classifier.pkl"))
    joblib.dump(vectorizer, os.path.join(MODEL_DIR, "vectorizer.pkl"))
    joblib.dump(le, os.path.join(MODEL_DIR, "label_encoder.pkl"))
    print("✅ Company-level model artifacts saved to /model/")