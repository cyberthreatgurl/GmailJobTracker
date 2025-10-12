import pandas as pd
import re
import json
from difflib import SequenceMatcher
from db import get_db_connection, PATTERNS_PATH, COMPANIES_PATH, is_valid_company
import argparse
import csv
from datetime import datetime

parser = argparse.ArgumentParser(description="Detect alias candidates from company names")
parser.add_argument("--export", help="Path to export alias suggestions (JSON or CSV)")
args = parser.parse_args()

# --- Config ---
MIN_COUNT = 1  # flag companies with <= this many occurrences
SIMILARITY_THRESHOLD = 0.75  # 0..1, higher = stricter match
DEBUG = True  # set True to enable verbose debug prints

# --- Load raw company names from DB ---
def load_raw_companies():
    conn = get_db_connection()
    query = """
        SELECT DISTINCT a.company, COUNT(*) as count, a.thread_id, m.subject
        FROM applications a
        JOIN tracker_message m ON a.thread_id = m.thread_id
        WHERE a.company IS NOT NULL
            AND a.company != ''
            AND (m.ml_label IS NULL OR m.ml_label NOT IN ('noise', 'job_alert'))
        GROUP BY a.company, a.thread_id, m.subject
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- Heuristic: looks like a clean company name ---
def is_clean_company(name):
    if not name or not name.strip():
        return False
    # Short (<= 4 words), no obvious job/status keywords
    if len(name.split()) > 4:
        return False
    if re.search(r'(interview|application|position|received|manager|engineer|researcher|job|role|title|follow-up)', name, re.I):
        return False
    return True

# --- Similarity helper ---
def similar(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# additional heuristics
PERSONAL_NAME_RE = re.compile(r'^[A-Z][a-z]{1,20} [A-Z][a-z]{1,20}$')
NOISE_TOKEN_RE = re.compile(r'(please|sign|attached|thanks|thank you|sincerely|regards|cv|resume|mr|ms|mrs)', re.I)

def is_personal_name_candidate(name):
    # loose personal-name detector: two capitalized words and not corporate suffix
    if not name:
        return False
    name_stripped = name.strip()
    parts = name_stripped.split()
    if len(parts) != 2:
        return False
    if not PERSONAL_NAME_RE.match(name_stripped):
        return False
    # allow through common corporate suffixes
    if re.search(r'\b(Inc|LLC|Ltd|Corp|Company|Co\.|PLC|Systems|Technologies|Group|Holdings)\b', name_stripped, re.I):
        return False
    # avoid flagging likely short brand names that are two words if any token contains a non-name char
    if any(re.search(r'[^A-Za-z\-]', p) for p in parts):
        return False
    # require tokens not to be excessively long
    if max(len(parts[0]), len(parts[1])) > 18:
        return False
    return True

def token_set_overlap(a, b):
    a_tokens = {t for t in re.findall(r'[A-Za-z0-9&\-]+', (a or "").lower())}
    b_tokens = {t for t in re.findall(r'[A-Za-z0-9&\-]+', (b or "").lower())}
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)

def cleaned_candidate(name):
    if not name:
        return ""
    s = name

    # drop leading articles and leading/trailing noise
    s = re.sub(r'^\s*(the|a|an)\s+', '', s, flags=re.I)

    # remove common family-of-company phrases and parenthetical-like tails
    s = re.sub(r'\b(&\s*the\s+.*Family of Companies|Family of Companies|Family of|Group of Companies|Group of)\b', '', s, flags=re.I)
    s = re.sub(r'\b(,?\s*(Inc|LLC|Ltd|Corp|Co\.|Company|PLC|Systems|Technologies|Holdings|Group))\b', '', s, flags=re.I)

    # remove role/job-title fragments that sometimes got captured as company
    s = re.sub(r'\b(the\s+)?(senior|lead|principal|junior|machine learning|engineer|developer|manager|analyst|recruiter|consultant)\b', '', s, flags=re.I)

    # remove known noise tokens and punctuation
    s = re.sub(r'\b(Application|Interview|Update|Confirmation|Availability|Please|Attached|Signature|Sign|Resume|CV)\b', '', s, flags=re.I)
    s = re.sub(r'[^A-Za-z0-9&\- ]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()

    return s

def likely_noise(name):
    if not name:
        return True

    # role/title heavy -> noise
    if re.search(r'\b(senior|lead|principal|junior|machine learning|engineer|developer|manager|analyst|recruiter|intern)\b', name, re.I):
        return True

    # exclude very long strings or those containing typical message tokens
    if len(name.split()) > 8:
        return True
    if NOISE_TOKEN_RE.search(name):
        return True

    # lots of punctuation (more than 6 non-word, non-space, non-&- chars)
    if len(re.findall(r'[^\w\s&\-]', name)) > 6:
        return True

    return False

def best_canonical_by_overlap(name, canonical_names, min_overlap=0.4):
    best = None
    best_score = 0.0
    for canon in canonical_names:
        ov = token_set_overlap(name, canon)
        if ov > best_score:
            best_score = ov
            best = canon
    return (best, round(best_score, 2)) if best_score >= min_overlap else (None, 0.0)

# --- Main ---
if __name__ == "__main__":
    df = load_raw_companies()

    # Load patterns.json and companies.json
    try:
        with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
            with open(COMPANIES_PATH, "r", encoding="utf-8") as e:
                patterns = json.load(f)
                aliases = json.load(e)
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
    print(f"  candidates after initial filter: {len(candidates)}")

    # Drop candidates that fail global company validity check
    candidates = candidates[candidates["company"].apply(is_valid_company)]
    print(f"  candidates after is_valid_company filter: {len(candidates)}")

    if candidates.empty:
        print("\n✅ No new alias candidates found.")
    else:
        print("\n🔍 Potential alias mappings to add:")
        # Will collect final export rows
        export_data = []

        for idx, row in candidates.iterrows():
          
            name = row['company']
            count = row['count']
            
            # Fetch thread_id and subject for audit
            thread_id = df.iloc[idx]['thread_id'] if 'thread_id' in df.columns else None
            subject = df.iloc[idx]['subject'] if 'subject' in df.columns else None

            # skip obviously noisy candidates early (but log why)
            noisy = likely_noise(name)
            personal = is_personal_name_candidate(name)
            # cleaned fallback
            clean = cleaned_candidate(name)

            # 1) try exact/similarity-based canonical candidates
            sims = [canon for canon in canonical_names if similar(name, canon) >= SIMILARITY_THRESHOLD]
            best_canon = sims[0] if sims else None
            sim_score = round(similar(name, best_canon) if best_canon else 0.0, 2)

            # 2) if no good similarity match, try token-overlap based canonical matching (captures "UIC & the Bowhead...")
            if not best_canon:
                overlap_canon, overlap_score = best_canonical_by_overlap(name, canonical_names, min_overlap=0.35)
                if overlap_canon:
                    best_canon = overlap_canon
                    sim_score = overlap_score  # reuse sim_score field for export/decision
        
            clean_vs_name_overlap = token_set_overlap(clean, name)
            clean_shorter = 0 < len(clean) < len(name)

            # Log full candidate diagnostics when DEBUG
            if DEBUG:
                print("----")
                print(f'candidate: "{name}" (count={count})')
                print(f'  clean: "{clean}"')
                print(f'  best_canon: "{best_canon}" sim_score={sim_score}')
                print(f'  clean_vs_name_overlap={clean_vs_name_overlap}')
                print(f'  clean_shorter={clean_shorter}')
                print(f'  likely_noise={noisy} is_personal_name_candidate={personal}')

            # Decision rules (ordered by trust)
            suggestion = None
            reason = None

            # 1) If a canonical exists with good similarity, prefer it (>= 0.75)
            if best_canon and sim_score >= 0.75 and best_canon.lower() != name.lower():
                suggestion = best_canon
                reason = f"canonical_sim:{sim_score}"

            # 2) If cleaned is meaningfully simpler and looks clean, prefer cleaned
            elif clean and clean_shorter and is_clean_company(clean):
                if clean_vs_name_overlap >= 0.35 or len(clean.split()) <= 3:
                    if clean.lower() != name.lower():
                        suggestion = clean
                        reason = f"cleaned_overlap:{clean_vs_name_overlap}"

            # 3) If canonical exists but sim lower than 0.75 and cleaned is poor, still allow canonical if sim >= 0.6
            elif best_canon and 0.6 <= sim_score < 0.75 and best_canon.lower() != name.lower():
                suggestion = best_canon
                reason = f"weak_canonical_sim:{sim_score}"

            # 4) Skip clear personal-name candidates but allow organizations that include '&' or corporate suffixes
            if not suggestion and is_personal_name_candidate(name) and '&' not in name and re.search(
                r'\b(Inc|LLC|Ltd|Corp|Co\.|Company|PLC|Systems|Technologies|Group|Holdings)\b', name, re.I
            ) is None:
                if DEBUG:
                    print(f"  Skipping personal-name: {name}")
                continue

            # 5) If likely noise and no suggestion, skip
            if not suggestion and noisy:
                if DEBUG:
                    print(f'  SKIP: likely noise and no suggestion')
                continue

            if suggestion:
                print(f'  "{name}" -> "{suggestion}" [{reason}, count={count}]')
                
                export_data.append({
                    "alias": name,
                    "suggested": suggestion,
                    "count": count,
                    "similarity": sim_score,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat(timespec='seconds'),
                    "source_thread_id": thread_id,
                    "source_subject": subject
                })

                if DEBUG:
                    print(f'  ✅ Exported: "{name}" → "{suggestion}" | reason={reason} | thread_id={thread_id}')

        # Export if requested
        if args.export:
            if args.export.endswith(".json"):
                with open(args.export, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=2)
            elif args.export.endswith(".csv"):
                with open(args.export, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["alias", "suggested", "count", "similarity", "reason"])
                    writer.writeheader()
                    writer.writerows(export_data)

            print(f"✅ Exported {len(export_data)} alias suggestions to {args.export}")