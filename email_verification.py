"""
Email discovery and verification module with optional Hunter.io integration,
quota tracking, HTTP error resilience, and free manual/CSV verification fallback.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
import requests

from config import config
from logging_config import logger
from models import Lead, VerificationStatus, normalize_email

# RFC 5322 compliant basic email regex
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)

# Common disposable email providers to reject
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com", "yopmail.com"
}


class HunterClient:
    """Client for Hunter.io API with strict rate-limit, quota, and error handling."""

    BASE_URL = "https://api.hunter.io/v2"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 6):
        self.api_key = api_key or config.hunter_api_key
        self.timeout = timeout
        self.session = requests.Session()

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def get_account_usage(self) -> Dict[str, Any]:
        """Fetch monthly plan and usage limits."""
        if not self.is_configured():
            return {"status": "unconfigured", "message": "HUNTER_API_KEY is not set."}

        url = f"{self.BASE_URL}/account"
        params = {"api_key": self.api_key}

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            return self._handle_response(resp)
        except requests.exceptions.RequestException as e:
            logger.warning("Error fetching Hunter.io account usage: %s", e)
            return {"status": "error", "message": str(e)}

    def domain_search(self, domain: str, limit: int = 5) -> Dict[str, Any]:
        """Perform Hunter domain search to find company email patterns and addresses."""
        if not self.is_configured():
            return {"status": "unconfigured", "message": "Hunter API key not configured."}

        url = f"{self.BASE_URL}/domain-search"
        params = {"domain": domain, "limit": limit, "api_key": self.api_key}

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            return self._handle_response(resp)
        except requests.exceptions.RequestException as e:
            logger.warning("Network error calling Hunter domain search: %s", e)
            return {"status": "network_error", "message": str(e)}

    def find_email(self, domain: str, first_name: str, last_name: str) -> Dict[str, Any]:
        """Search Hunter for a specific person's email at a domain."""
        if not self.is_configured():
            return {"status": "unconfigured", "message": "Hunter API key not configured."}

        url = f"{self.BASE_URL}/email-finder"
        params = {
            "domain": domain,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": self.api_key,
        }

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            return self._handle_response(resp)
        except requests.exceptions.RequestException as e:
            logger.warning("Network error calling Hunter email finder: %s", e)
            return {"status": "network_error", "message": str(e)}

    def verify_email(self, email: str) -> Dict[str, Any]:
        """Verify deliverability of an email address using Hunter email verifier."""
        if not self.is_configured():
            return {"status": "unconfigured", "message": "Hunter API key not configured."}

        url = f"{self.BASE_URL}/email-verifier"
        params = {"email": email, "api_key": self.api_key}

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            return self._handle_response(resp)
        except requests.exceptions.RequestException as e:
            logger.warning("Network error calling Hunter email verifier: %s", e)
            return {"status": "network_error", "message": str(e)}

    def _handle_response(self, resp: requests.Response) -> Dict[str, Any]:
        """Defensively handle HTTP response codes and error formats."""
        if resp.status_code == 200:
            return {"status": "success", "data": resp.json().get("data", {})}
        elif resp.status_code == 401:
            logger.error("Hunter API 401 Unauthorized: Invalid or missing API key.")
            return {"status": "unauthorized", "message": "Hunter API Key is invalid or expired."}
        elif resp.status_code == 403:
            logger.warning("Hunter API 403 Forbidden: Endpoint restricted on current plan.")
            return {"status": "forbidden", "message": "Endpoint not permitted on your Hunter plan."}
        elif resp.status_code == 404:
            return {"status": "not_found", "message": "No matching record found in Hunter."}
        elif resp.status_code == 429:
            logger.warning("Hunter API 429: Monthly rate limit or quota exceeded.")
            return {"status": "quota_exceeded", "message": "Hunter monthly request quota exhausted."}
        else:
            logger.warning("Hunter API returned unexpected status %d", resp.status_code)
            return {"status": f"http_{resp.status_code}", "message": resp.text}


class EmailVerifier:
    """Orchestrates email verification, syntax validation, and manual fallbacks."""

    def __init__(self, hunter_client: Optional[HunterClient] = None):
        self.hunter = hunter_client or HunterClient()

    def validate_syntax(self, email: str) -> bool:
        """Check if email matches RFC 5322 syntax and is not from a disposable domain."""
        norm = normalize_email(email)
        if not norm or not EMAIL_REGEX.match(norm):
            return False
        domain = norm.split("@")[-1]
        if domain in DISPOSABLE_DOMAINS:
            return False
        return True

    def verify_lead_email(self, lead: Lead) -> Lead:
        """
        Verify the lead's email.
        If Hunter API is available, query Hunter verifier.
        Otherwise, use syntax validation and maintain status truthfully.
        """
        if not lead.email:
            lead.verification_status = VerificationStatus.MISSING
            return lead

        # First check syntax
        if not self.validate_syntax(lead.email):
            lead.verification_status = VerificationStatus.INVALID
            lead.notes = f"{lead.notes} | Invalid email syntax or disposable domain".strip(" |")
            return lead

        # If already explicitly verified manually, retain VERIFIED status
        if lead.verification_status == VerificationStatus.VERIFIED and "verified" in lead.email_source.lower():
            return lead

        # If Hunter API is configured, verify deliverability
        if self.hunter.is_configured():
            result = self.hunter.verify_email(lead.email)
            if result.get("status") == "success":
                data = result.get("data", {})
                h_status = data.get("status", "")  # valid, invalid, accept_all, webmail, unknown
                score = data.get("score", 0)

                if h_status == "valid" and score >= 70:
                    lead.verification_status = VerificationStatus.VERIFIED
                    lead.email_source = f"{lead.email_source} (Hunter verified: score {score})".strip()
                elif h_status == "invalid":
                    lead.verification_status = VerificationStatus.INVALID
                else:
                    # accept_all or unknown - never represent as verified deliverable
                    lead.verification_status = VerificationStatus.UNVERIFIED
                return lead
            elif result.get("status") == "quota_exceeded":
                logger.info("Hunter quota exhausted; keeping status as %s", lead.verification_status.value)
            elif result.get("status") in ("unauthorized", "forbidden"):
                logger.info("Hunter API unavailable (%s); maintaining current verification status", result.get("status"))

        # Default fallback: if syntax is good but not externally verified, keep UNVERIFIED
        if lead.verification_status not in (VerificationStatus.VERIFIED, VerificationStatus.INVALID):
            lead.verification_status = VerificationStatus.UNVERIFIED

        return lead

    def record_manual_email(
        self,
        lead: Lead,
        email: str,
        source_url: str,
        is_verified: bool = False,
        notes: str = "",
    ) -> Lead:
        """
        Records a manually verified or sourced professional email with source attribution.
        Never guesses naming conventions.
        """
        norm_email = normalize_email(email)
        if not self.validate_syntax(norm_email):
            lead.email = norm_email
            lead.verification_status = VerificationStatus.INVALID
            return lead

        lead.email = norm_email
        lead.email_source = source_url or "Direct Company Website"
        lead.verification_status = VerificationStatus.VERIFIED if is_verified else VerificationStatus.UNVERIFIED
        if notes:
            lead.notes = f"{lead.notes} | {notes}".strip(" |")

        logger.info(
            "Recorded email %s for %s (Status: %s, Source: %s)",
            lead.email, lead.company, lead.verification_status.value, lead.email_source
        )
        return lead


email_verifier = EmailVerifier()
