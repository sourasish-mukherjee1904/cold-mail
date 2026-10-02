"""
Decision-maker contact discovery and role prioritization.
Prioritizes technical leaders (CTO, AI/ML Leads, Founders) and records verifiable source URLs.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from logging_config import logger
from models import Lead, VerificationStatus

# Priority weights for decision-maker roles (higher score = more relevant for technical internship)
ROLE_PRIORITIES = [
    (re.compile(r"\b(cto|chief technology officer|technical director)\b", re.IGNORECASE), 100, "CTO / Technical Director"),
    (re.compile(r"\b(head of ai|ai lead|head of ml|head of machine learning|director of ai|ai research lead)\b", re.IGNORECASE), 95, "AI/ML Lead"),
    (re.compile(r"\b(head of engineering|vp engineering|director of engineering)\b", re.IGNORECASE), 90, "Head of Engineering"),
    (re.compile(r"\b(co-founder & ceo|founder & ceo|co-founder|founder|ceo)\b", re.IGNORECASE), 85, "Founder / CEO"),
    (re.compile(r"\b(engineering manager|lead software engineer|principal engineer)\b", re.IGNORECASE), 80, "Engineering Manager"),
    (re.compile(r"\b(technical recruiter|talent acquisition lead|hr manager|head of people)\b", re.IGNORECASE), 60, "Technical Hiring / HR"),
]


def score_role_priority(designation: str) -> Tuple[int, str]:
    """Scores the relevance of a contact's role for an AI/ML engineering internship."""
    if not designation:
        return 0, "Unknown Role"
    for pattern, score, category in ROLE_PRIORITIES:
        if pattern.search(designation):
            return score, category
    return 40, "General Role"


class ContactDiscovery:
    """Manages finding, prioritizing, and assigning decision-makers to company leads."""

    def assign_contact(
        self,
        lead: Lead,
        name: str,
        designation: str,
        profile_url: str = "",
        email: str = "",
        source_url: str = "",
        is_verified: bool = False,
    ) -> Lead:
        """
        Assigns a verified or discovered professional contact to a company lead.
        Ensures name, designation, and source information are recorded accurately.
        """
        if not name.strip():
            logger.warning("Attempted to assign empty contact name for %s", lead.company)
            return lead

        lead.person_name = name.strip()
        lead.designation = designation.strip()
        lead.professional_profile_url = profile_url.strip()
        lead.company_source = source_url.strip() or lead.company_source
        lead.source_date = datetime.date.today().isoformat()

        if email.strip():
            lead.email = email.strip().lower()
            lead.email_source = source_url.strip() or "Direct Contact Listing"
            lead.verification_status = VerificationStatus.VERIFIED if is_verified else VerificationStatus.UNVERIFIED
        else:
            lead.verification_status = VerificationStatus.MISSING

        score, category = score_role_priority(lead.designation)
        logger.info(
            "Assigned contact '%s' (%s, priority %d) to %s",
            lead.person_name, category, score, lead.company
        )
        return lead


contact_discovery = ContactDiscovery()
