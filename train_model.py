import joblib
import pandas as pd
from db import load_training_data
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer

# --- Load pre-cleaned training data from db.py ---
df = load_training_data()

print(f"📦 Dataset ready for training: {df.shape[0]} rows")
print(df.head())

# --- Prepare text field for vectorization ---
df['text'] = df['subject'].fillna('') + ' ' + df['body'].fillna('')

# --- Encode labels ---
le = LabelEncoder()
df['company_encoded'] = le.fit_transform(df['company'])

# --- Filter sparse classes ---
# Keep only companies with at least 2 samples so train/test split works
company_counts = df['company'].value_counts()
df = df[df['company'].isin(company_counts[company_counts > 1].index)]

# Re-encode after filtering
le = LabelEncoder()
df['company_encoded'] = le.fit_transform(df['company'])

# --- Debug: show class distribution ---
print("📊 Company label distribution:", df['company'].value_counts())
print("🔢 Encoded label distribution:", pd.Series(df['company_encoded']).value_counts())

# --- Safety check: ensure at least 2 classes remain ---
unique_labels = set(df['company_encoded'])
if len(unique_labels) < 2:
    print("🚫 Only one unique company label remains after filtering:")
    print(df[['company', 'company_encoded']].drop_duplicates())
    df.to_csv("model/last_cleaned_training_data.csv", index=False)
    print("💾 Saved cleaned dataset to model/last_cleaned_training_data.csv for review.")
    print("⚠️ Skipping ML training — not enough classes to train a classifier.")
    exit(0)

# --- Vectorize text ---
vectorizer = TfidfVectorizer(
    stop_words='english',
    max_features=5000,
    ngram_range=(1, 2)
)
X = vectorizer.fit_transform(df['text'])
y = df['company_encoded']

# --- Train/test split ---
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# --- Train model ---
clf = LogisticRegression(max_iter=1000, class_weight='balanced')
clf.fit(X_train, y_train)

# --- Evaluate ---
y_pred = clf.predict(X_test)
labels_in_test = sorted(set(y_test))
target_names = le.inverse_transform(labels_in_test)
print(classification_report(y_test, y_pred, labels=labels_in_test, target_names=target_names))

# --- Save artifacts ---
joblib.dump(clf, 'model/company_classifier.pkl')
joblib.dump(vectorizer, 'model/vectorizer.pkl')
joblib.dump(le, 'model/label_encoder.pkl')
print("✅ Model artifacts saved to /model/")