"""Domain mapping and ATS detection for email messages.

This module contains the DomainMapper class which handles domain-to-company mapping,
ATS domain detection, and automatic reloading of company data when files change.
"""

import json
from pathlib import Path
from typing import Optional


DEBUG = False  # Set to True for verbose domain mapping debugging


class DomainMapper:
    """Maps email domains to companies and detects ATS/job board domains.
    
    This class encapsulates domain resolution logic, company data loading,
    and automatic reloading when the companies.json file changes.
    """

    def __init__(self, companies_path: Path):
        """Initialize DomainMapper with path to companies.json.
        
        Args:
            companies_path: Path to companies.json configuration file
        """
        self.companies_path = companies_path
        self._domain_map_mtime: Optional[float] = None
        
        # Company data structures
        self.ats_domains: list[str] = []
        self.headhunter_domains: list[str] = []
        self.job_board_domains: list[str] = []
        self.known_companies: set[str] = set()
        self.known_companies_cased: list[str] = []
        self.domain_to_company: dict[str, str] = {}
        self.aliases: dict[str, str] = {}
        self.company_data: dict = {}
        
        # Load initial data
        self._load_company_data()

    def _load_company_data(self):
        """Load company data from companies.json file."""
        if not self.companies_path.exists():
            if DEBUG:
                print(f"[WARNING] companies.json not found at {self.companies_path}")
            return
        
        try:
            with open(self.companies_path, "r", encoding="utf-8") as f:
                self.company_data = json.load(f)
            
            # Extract all company configuration data
            self.ats_domains = [d.lower() for d in self.company_data.get("ats_domains", [])]
            self.headhunter_domains = [d.lower() for d in self.company_data.get("headhunter_domains", [])]
            self.job_board_domains = [d.lower() for d in self.company_data.get("job_boards", [])]
            self.known_companies = {c.lower() for c in self.company_data.get("known", [])}
            self.known_companies_cased = self.company_data.get("known", [])
            self.domain_to_company = {
                k.lower(): v for k, v in self.company_data.get("domain_to_company", {}).items()
            }
            self.aliases = self.company_data.get("aliases", {})
            
            # Track file modification time for auto-reload
            try:
                self._domain_map_mtime = self.companies_path.stat().st_mtime
            except Exception:
                self._domain_map_mtime = None
                
            if DEBUG:
                print(f"[INFO] Loaded companies.json: {len(self.domain_to_company)} domains, "
                      f"{len(self.known_companies)} companies")
                
        except json.JSONDecodeError as e:
            print(f"[Error] Failed to parse companies.json: {e}")
            self.company_data = {}
        except Exception as e:
            print(f"[Error] Unable to read companies.json: {e}")
            self.company_data = {}

    def reload_if_needed(self):
        """Reload company data from companies.json if the file has been modified.
        
        This allows companies.json edits to be picked up at runtime without
        restarting the process.
        """
        try:
            if not self.companies_path.exists():
                return
            
            mtime = self.companies_path.stat().st_mtime
            if self._domain_map_mtime != mtime:
                self._load_company_data()
                if DEBUG:
                    print(f"[INFO] Reloaded companies.json (mtime changed)")
        except Exception as e:
            # If reload fails, keep the existing mapping silently
            if DEBUG:
                print(f"[WARNING] Failed to reload companies.json: {e}")

    def is_ats_domain(self, domain: str) -> bool:
        """Return True if domain equals or is a subdomain of any ATS root domain.
        
        Args:
            domain: Email domain to check (e.g., 'myworkday.com', 'talent.icims.com')
            
        Returns:
            True if domain is an ATS domain, False otherwise
        """
        if not domain:
            return False
        d = domain.lower()
        for ats in self.ats_domains:
            if d == ats or d.endswith("." + ats):
                return True
        return False

    def map_company_by_domain(self, domain: str) -> Optional[str]:
        """Resolve company by exact or subdomain match from domain_to_company mapping.

        Example: if mapping contains 'nsa.gov' -> 'National Security Agency', then
        'uwe.nsa.gov' will also map to that company.
        
        Args:
            domain: Email domain to resolve (e.g., 'careers.company.com')
            
        Returns:
            Company name if domain maps to a known company, None otherwise
        """
        # Ensure we have the latest mapping
        self.reload_if_needed()
        
        if not domain:
            return None
        
        d = domain.lower()
        
        # Exact match first
        if d in self.domain_to_company:
            return self.domain_to_company[d]
        
        # Subdomain suffix match
        for root, company in self.domain_to_company.items():
            if d.endswith("." + root):
                return company
        
        return None

    def is_job_board_domain(self, domain: str) -> bool:
        """Return True if domain is a known job board domain.
        
        Args:
            domain: Email domain to check
            
        Returns:
            True if domain is a job board, False otherwise
        """
        if not domain:
            return False
        return domain.lower() in self.job_board_domains

    def is_headhunter_domain(self, domain: str) -> bool:
        """Return True if domain is a known headhunter/recruiting agency domain.
        
        Args:
            domain: Email domain to check
            
        Returns:
            True if domain is a headhunter domain, False otherwise
        """
        if not domain:
            return False
        return domain.lower() in self.headhunter_domains
