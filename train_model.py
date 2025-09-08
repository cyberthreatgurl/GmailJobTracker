import joblib
import re
import pandas as pd
from db import load_training_data
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer

def normalize_company(name):
    # Lowercase for uniformity
    name = name.strip()
    # Remove leading job titles like "Security Architect at ..."
    match = re.search(r'\b(?:at|@)\s+(.+)$', name, flags=re.IGNORECASE)
    
    if match:
        name = match.group(1)
    return name.strip()

def is_valid_company(name):
    name = name.strip()
    # Reject if it starts with lowercase or contains pronouns
    if re.match(r'^[a-z]', name): return False
    if re.search(r'\b(your|you|position|manager|engineer|researcher|job|role|title)\b', name, re.I): return False
    # Reject if it's longer than 5 words (likely a sentence)
    if len(name.split()) > 5: return False
    return True

df = load_training_data()

# Clean and filter data
df['company'] = df['company'].apply(normalize_company)
df = df[df['company'].str.len() > 3]  # Remove short or placeholder labels
df = df[~df['company'].str.contains(r'thank you|evaluate|job|sr|intelligence', case=False)]
df = df[df['company'].apply(is_valid_company)]

invalids = df[~df['company'].apply(is_valid_company)]
print("🧹 Dropped invalid company labels:")
print(invalids['company'].value_counts())
print(df.shape)
print(df.head())

# filter sparese classes
#
df['text'] = df['subject'].fillna('') + ' ' + df['body'].fillna('')

le = LabelEncoder()
df['company_encoded'] = le.fit_transform(df['company'])

# Filter sparse classes BEFORE encoding
company_counts = df['company'].value_counts()
df = df[df['company'].isin(company_counts[company_counts > 0].index)]

# Combine subject + body
df['text'] = df['subject'].fillna('') + ' ' + df['body'].fillna('')

# Encode labels AFTER filtering
le = LabelEncoder()
df['company_encoded'] = le.fit_transform(df['company'])

print("📊 Company label distribution:", df['company'].value_counts())
print("🔢 Encoded label distribution:", pd.Series(df['company_encoded']).value_counts())

label_counts = pd.Series(df['company_encoded']).value_counts()
valid_labels = label_counts[label_counts > 1].index
df = df[df['company_encoded'].isin(valid_labels)]

# Vectorize text
vectorizer = TfidfVectorizer(
    stop_words='english',
    max_features=5000,
    ngram_range=(1, 2)
)
X = vectorizer.fit_transform(df['text'])
y = df['company_encoded']

unique_labels = set(df['company_encoded'])
if len(unique_labels) < 2:
    print("🚫 Only one unique company label remains after filtering:")
    print(df[['company', 'company_encoded']].drop_duplicates())
    raise ValueError("Cannot train classifier with only one class.")

if len(unique_labels) < 2:
    raise ValueError(f"🚫 Only one unique company label found ({list(unique_labels)}). Cannot train classifier.")

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# Train model with class balancing
clf = LogisticRegression(max_iter=1000, class_weight='balanced')
clf.fit(X_train, y_train)

y_pred = clf.predict(X_test)
labels_in_test = sorted(set(y_test))  # Unique label indices in test set
target_names = le.inverse_transform(labels_in_test)

print(classification_report(y_test, y_pred, labels=labels_in_test, target_names=target_names))

# Save model artifacts
# 
joblib.dump(clf, 'model/company_classifier.pkl')
joblib.dump(vectorizer, 'model/vectorizer.pkl')
joblib.dump(le, 'model/label_encoder.pkl')
print("✅ Model artifacts saved to /model/")
