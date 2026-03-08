
import re
import logging
from bs4 import BeautifulSoup

# Mock logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("parser")

class CompanyValidator:
    def is_valid_company_name(self, name):
        return True # Mock validation
    
    def normalize_company_name(self, name):
        return name

class CompanyResolver:
    def __init__(self):
        self.company_validator = CompanyValidator()
        self.ats_domains = ["myworkday.com", "greenhouse.io"]

    def extract_from_ats_body_patterns(self, body, subject, sender_domain):
        if not body:
            return None

        domain_lower = (sender_domain or "").lower()

        logger.debug("[DEBUG] Entering ATS body pattern extraction")
        body_plain = body
        try:
            if "<html" in body.lower() or "<style" in body.lower():
                soup = BeautifulSoup(body, "html.parser")
                for tag in soup(["style", "script"]):
                    tag.decompose()
                body_plain = soup.get_text(separator=" ", strip=True)
        except Exception:
            body_plain = body
            
        print(f"PLAIN BODY: {body_plain}")

        ats_body_patterns = [
            r"position\s+(?:here\s+)?at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)"
            r"(?:\.|,|[\r\n]|\s+Thank|\s+you\b)",
            
            r"position\s+(?:here\s+)?(?:at|with)\s+"
            r"([A-Z][A-Za-z0-9\s&.,'-]{2,30})(?:\.|,|[\r\n])",
            
            r"application\s+for\s+(?:our|the)\s+.{5,50}?\s+at\s+"
            r"([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\.|[\r\n])",
            
            r"considering\s+us\s+at\s+"
            r"([A-Z][A-Za-z0-9\s&.,'-]+?)\s+as",
            
            r"considering\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s+as\s+"
            r"(?:a\s+)?(?:potential|future)\s+employer",
            
            r"(?:your\s+)?interest\s+in\s+(?:the\s+)?"
            r"([A-Z][A-Za-z0-9\s&.,'-]{2,60}?)"
            r"(?:\s+(?:and\s+(?:apply|applying|applied)"
            r"|to\s+(?:the\s+)?(?:role|position)"
            r"|for\s+(?:the\s+)?(?:role|position)"
            r"|for\s+this\s+job)|\.|!|[\r\n])",
        ]

        for i, pattern in enumerate(ats_body_patterns):
            ats_match = re.search(pattern, body_plain, re.IGNORECASE)
            if ats_match:
                print(f"MATCHED PATTERN #{i}: {pattern}")
                extracted = ats_match.group(1).strip()
                print(f"RAW EXTRACTED: '{extracted}'")
                
                # Trim common trailing clauses accidentally captured
                # ... (Logic from original file) ...
                return extracted
        return None

body_text = """Dear Kelly, Thank you for applying to the Senior Cyber Engineer opportunity. If your background matches what we are looking for, we will reach out to you to discuss next steps. Thank you again for considering this opportunity. All the best, The Red River Recruiting Team"""

resolver = CompanyResolver()
company = resolver.extract_from_ats_body_patterns(body_text, "Subject", "myworkday.com")
print(f"EXTRACTED COMPANY: '{company}'")
