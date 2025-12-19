"""Machine learning-based entity extraction for company and job title identification."""

# ml_entity_extraction.py

import spacy

# Load spaCy model (custom or pre-trained)
nlp = spacy.load("en_core_web_sm")


def extract_entities(subject):
    """Extract company and job title entities from message subject using spaCy NER."""
    doc = nlp(subject)
    company = ""
    job_title = ""

    for ent in doc.ents:
        if ent.label_ == "ORG":
            company = ent.text
        elif ent.label_ in ["JOB_TITLE", "WORK_OF_ART", "PRODUCT"]:
            job_title = ent.text

    return {
        "company": company,
        "job_title": job_title,
        "location": "",  # Optional: add LOC support
    }
