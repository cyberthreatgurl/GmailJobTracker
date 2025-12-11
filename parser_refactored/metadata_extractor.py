"""
Metadata Extractor Module

Extracts metadata from email messages including:
- Status dates (application, rejection, interview, follow-up)
- iCalendar organizer information
- Job IDs from subject lines
"""

import re
import base64
from datetime import timedelta
from typing import Dict, Optional, Tuple, Any


class MetadataExtractor:
    """Extract dates, job IDs, and other metadata from email messages."""

    def __init__(self, rule_classifier=None, debug: bool = False):
        """
        Initialize MetadataExtractor.
        
        Args:
            rule_classifier: RuleClassifier instance for accessing compiled patterns
            debug: Enable debug logging
        """
        self._rule_classifier = rule_classifier
        self._debug = debug

    def extract_status_dates(self, body: str, received_date) -> Dict[str, Any]:
        """
        Extract key status dates from email body.
        
        For interview invites, sets interview_date to 7 days in the future
        to mark as "upcoming" (user can manually update with actual date).
        
        Args:
            body: Email body text
            received_date: Date the email was received
            
        Returns:
            Dictionary with response_date, rejection_date, interview_date, follow_up_dates
        """
        body_lower = body.lower()
        dates = {
            "response_date": None,
            "rejection_date": None,
            "interview_date": None,
            "follow_up_dates": [],
        }
        
        if not self._rule_classifier:
            return dates
        
        # Use compiled patterns from RuleClassifier instance
        interview_patterns = self._rule_classifier._msg_label_patterns.get("interview_invite", [])
        rejection_patterns = self._rule_classifier._msg_label_patterns.get("rejection", [])
        response_patterns = self._rule_classifier._msg_label_patterns.get("response", [])
        followup_patterns = self._rule_classifier._msg_label_patterns.get("follow_up", [])
        
        if any(re.search(p, body_lower) for p in response_patterns):
            dates["response_date"] = received_date
        if any(re.search(p, body_lower) for p in rejection_patterns):
            dates["rejection_date"] = received_date
        if any(re.search(p, body_lower) for p in interview_patterns):
            # Set to 7 days in future to mark as "upcoming interview"
            dates["interview_date"] = (received_date + timedelta(days=7)).date()
        if any(re.search(p, body_lower) for p in followup_patterns):
            dates["follow_up_dates"] = received_date
        return dates

    @staticmethod
    def extract_organizer_from_icalendar(body: str, debug: bool = False) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract organizer email from iCalendar data in message body.
        
        Teams/Zoom meeting invites often contain BASE64 encoded iCalendar data
        with ORGANIZER field containing the sender's email address.
        
        Args:
            body: Email body text (may contain BASE64 encoded iCalendar data)
            debug: Enable debug logging
            
        Returns:
            Tuple of (organizer_email, organizer_domain) or (None, None)
        """
        if not body:
            return None, None
        
        # Look for BASE64 encoded iCalendar data
        # Pattern: continuous BASE64 string (common in calendar invites)
        base64_pattern = r'(?:[A-Za-z0-9+/]{60,}\n?)+'
        matches = re.findall(base64_pattern, body)
        
        for match in matches:
            try:
                # Remove newlines and decode
                base64_data = match.replace('\n', '').replace('\r', '')
                decoded = base64.b64decode(base64_data).decode('utf-8', errors='ignore')
                
                # Check if this is iCalendar data
                if 'BEGIN:VCALENDAR' in decoded or 'ORGANIZER' in decoded:
                    # Extract ORGANIZER email
                    # Format: ORGANIZER;CN=Name:mailto:email@domain.com
                    organizer_match = re.search(
                        r'ORGANIZER[^:]*:mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                        decoded,
                        re.IGNORECASE
                    )
                    if organizer_match:
                        email = organizer_match.group(1).lower()
                        domain = email.split('@')[-1] if '@' in email else None
                        if debug:
                            print(f"[DEBUG] Extracted organizer from iCalendar: {email} (domain: {domain})")
                        return email, domain
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Failed to decode/parse iCalendar data: {e}")
                continue
        
        return None, None

    @staticmethod
    def extract_job_id(subject: str) -> str:
        """
        Extract job ID from subject line.
        
        Looks for patterns like:
        - Job #12345
        - Position #ABC-123
        - jobId=XYZ789
        
        Args:
            subject: Email subject line
            
        Returns:
            Job ID string or empty string if not found
        """
        if not subject:
            return ""
        
        id_match = re.search(r"(?:Job\s*#?|Position\s*#?|jobId=)([\w\-]+)", subject, re.IGNORECASE)
        return id_match.group(1).strip() if id_match else ""
