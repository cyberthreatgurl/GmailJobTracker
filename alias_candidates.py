import pandas as pd
import re
import json
from difflib import SequenceMatcher
from db import get_db_connection, PATTERNS_PATH, COMPANIES_PATH

# --- Config ---
MIN_COUNT = 1  # flag companies with <= this many occurrences
SIMILARITY_THRESHOLD = 0.75  # 0..1, higher = stricter match

# --- Load raw company names from DB ---
def load_raw_companies():
    conn = get_db_connection()
    query = """
        SELECT DISTINCT a.company, COUNT(*) as count
        FROM applications a
        WHERE a.company IS NOT NULL AND a.company != ''
        GROUP BY a.company
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- Heuristic: looks like a clean company name ---
def is_clean_company(name):
    # Short (<= 4 words), no obvious job/status keywords
    if len(name.split()) > 4:
        return False
    if re.search(r'(interview|application|position|received|manager|engineer|researcher|job|role|title|follow-up)', name, re.I):
        return False
    return True

# --- Similarity helper ---
def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# --- Main ---
if __name__ == "__main__":
    df = load_raw_companies()

    # Load patterns.json amd companies.json
    try:
        with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
            with open(COMPANIES_PATH, "r", encoding="utf-8") as e:
                aliases = json.load(e)    
                patterns = json.load(f)
    except FileNotFoundError:
        patterns = {}
        aliases = {}
    ignore_patterns = set(p.lower() for p in patterns.get("ignore", []))
    existing_aliases = set(aliases.get("aliases", {}).keys())
    canonical_names = set(aliases.get("aliases", {}).values())

    print(f"📊 Found {len(df)} unique company names in DB")
    print(f"📂 Existing aliases in patterns.json: {len(existing_aliases)}")
    print(f"🚫 Ignoring {len(ignore_patterns)} patterns from patterns.json")

    # Filter: low-frequency, not ignored, not already an alias, not clean
    candidates = df[
        (df['count'] <= MIN_COUNT) &
        (~df['company'].isin(existing_aliases)) &
        (~df['company'].str.lower().isin(ignore_patterns)) &
        (~df['company'].apply(is_clean_company))
    ]

    if candidates.empty:
        print("\n✅ No new alias candidates found.")
    else:
        print("\n🔍 Potential alias mappings to add:")
        for _, row in candidates.iterrows():
            name = row['company']
            count = row['count']

            # Suggest similar canonical names
            sims = [
                canon for canon in canonical_names
                if similar(name, canon) >= SIMILARITY_THRESHOLD
            ]
            sim_note = f" → similar to {', '.join(sims)}" if sims else ""

            # Heuristic: strip known suffixes like "Application", "Interview", "Update"
            clean = re.sub(r'\b(Application|Interview|Update|Confirmation|Availability)\b', '', name, flags=re.I).strip()
            clean = re.sub(r'[^A-Za-z0-9&\- ]+', '', clean).strip()

            # If clean name is short and looks like a company, suggest it
            if is_clean_company(clean) and clean.lower() != name.lower():
                print(f'  "{name}": "{clean}"')
            elif sims:
                print(f'  "{name}": "{sims[0]}"{sim_note}')