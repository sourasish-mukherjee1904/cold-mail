"""
Domain data models and schemas for the Winter Internship Outreach System.
Includes strict typing, enumerations, validation, and exact 29-column row serialization.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OutreachStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DRAFT_CREATED = "DRAFT_CREATED"
    SENT = "SENT"
    OPTED_OUT = "OPTED_OUT"


# The exact 29 Google Sheets header names in specified order
SHEET_HEADERS = [
    "lead_id",
    "company",
    "website",
    "domain",
    "description",
    "industry",
    "location",
    "company_size",
    "company_source",
    "source_date",
    "person_name",
    "designation",
    "professional_profile_url",
    "email",
    "email_source",
    "verification_status",
    "relevance_score",
    "relevance_reason",
    "personalization_fact",
    "personalization_source",
    "subject",
    "email_body",
    "approval_status",
    "outreach_status",
    "gmail_draft_id",
    "last_contacted",
    "follow_up_date",
    "opt_out",
    "notes",
]


def normalize_domain(url_or_domain: Optional[str]) -> str:
    """Extract and normalize domain from URL or domain string."""
    if not url_or_domain:
        return ""
    cleaned = url_or_domain.strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = re.sub(r"^www\.", "", cleaned)
    cleaned = cleaned.split("/")[0].split("?")[0].strip()
    return cleaned


def normalize_email(email: Optional[str]) -> str:
    """Normalize email address to lowercase stripped."""
    if not email:
        return ""
    return email.strip().lower()


def generate_lead_id(company_domain: str, email_or_name: str) -> str:
    """
    Generate a stable, deterministic lead ID based on domain and email or contact name.
    Ensures idempotency across multiple runs.
    """
    norm_domain = normalize_domain(company_domain)
    norm_ident = normalize_email(email_or_name)
    raw = f"{norm_domain}:{norm_ident}".encode("utf-8")
    return f"lead_{hashlib.sha256(raw).hexdigest()[:12]}"


class Lead(BaseModel):
    """Represents a unified company + decision-maker lead record."""

    # 1-10: Company details
    lead_id: str = Field(default="")
    company: str = Field(..., min_length=1)
    website: str = Field(default="")
    domain: str = Field(default="")
    description: str = Field(default="")
    industry: str = Field(default="")
    location: str = Field(default="")
    company_size: str = Field(default="")
    company_source: str = Field(default="")
    source_date: str = Field(default_factory=lambda: datetime.date.today().isoformat())

    # 11-16: Contact & Email details
    person_name: str = Field(default="")
    designation: str = Field(default="")
    professional_profile_url: str = Field(default="")
    email: str = Field(default="")
    email_source: str = Field(default="")
    verification_status: VerificationStatus = Field(default=VerificationStatus.MISSING)

    # 17-20: Relevance & Personalization
    relevance_score: int = Field(default=0, ge=0, le=100)
    relevance_reason: str = Field(default="")
    personalization_fact: str = Field(default="")
    personalization_source: str = Field(default="")

    # 21-22: Email Draft Content
    subject: str = Field(default="")
    email_body: str = Field(default="")

    # 23-29: Outreach Management & Tracking
    approval_status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    outreach_status: OutreachStatus = Field(default=OutreachStatus.NOT_STARTED)
    gmail_draft_id: str = Field(default="")
    last_contacted: str = Field(default="")
    follow_up_date: str = Field(default="")
    opt_out: bool = Field(default=False)
    notes: str = Field(default="")

    @model_validator(mode="after")
    def post_validate_and_normalize(self) -> Lead:
        # Normalize domain
        if not self.domain and self.website:
            self.domain = normalize_domain(self.website)
        elif self.domain:
            self.domain = normalize_domain(self.domain)

        # Normalize email
        if self.email:
            self.email = normalize_email(self.email)
            if self.verification_status == VerificationStatus.MISSING:
                self.verification_status = VerificationStatus.UNVERIFIED
        else:
            self.verification_status = VerificationStatus.MISSING

        # Generate lead_id if empty
        if not self.lead_id:
            ident = self.email if self.email else self.person_name or self.company
            self.lead_id = generate_lead_id(self.domain or self.company, ident)

        # Sync opt_out outreach_status
        if self.opt_out:
            self.outreach_status = OutreachStatus.OPTED_OUT

        return self

    def to_sheet_row(self) -> List[Any]:
        """Convert lead record to an exact 29-element list matching SHEET_HEADERS."""
        return [
            self.lead_id,
            self.company,
            self.website,
            self.domain,
            self.description,
            self.industry,
            self.location,
            self.company_size,
            self.company_source,
            self.source_date,
            self.person_name,
            self.designation,
            self.professional_profile_url,
            self.email,
            self.email_source,
            self.verification_status.value if isinstance(self.verification_status, VerificationStatus) else str(self.verification_status),
            self.relevance_score,
            self.relevance_reason,
            self.personalization_fact,
            self.personalization_source,
            self.subject,
            self.email_body,
            self.approval_status.value if isinstance(self.approval_status, ApprovalStatus) else str(self.approval_status),
            self.outreach_status.value if isinstance(self.outreach_status, OutreachStatus) else str(self.outreach_status),
            self.gmail_draft_id,
            self.last_contacted,
            self.follow_up_date,
            "TRUE" if self.opt_out else "FALSE",
            self.notes,
        ]

    @classmethod
    def from_sheet_row(cls, row: List[Any]) -> Lead:
        """Construct Lead from a row of up to 29 values."""
        # Pad row with empty strings if shorter than 29
        padded = list(row) + [""] * (len(SHEET_HEADERS) - len(row))
        d: Dict[str, Any] = {}
        for idx, key in enumerate(SHEET_HEADERS):
            val = padded[idx]
            if key == "relevance_score":
                try:
                    d[key] = int(val) if val != "" else 0
                except (ValueError, TypeError):
                    d[key] = 0
            elif key == "opt_out":
                d[key] = str(val).strip().upper() in ("TRUE", "1", "YES", "T")
            elif key == "verification_status":
                cleaned = str(val).strip().upper()
                d[key] = VerificationStatus(cleaned) if cleaned in VerificationStatus.__members__ else VerificationStatus.UNKNOWN
            elif key == "approval_status":
                cleaned = str(val).strip().upper()
                d[key] = ApprovalStatus(cleaned) if cleaned in ApprovalStatus.__members__ else ApprovalStatus.PENDING
            elif key == "outreach_status":
                cleaned = str(val).strip().upper()
                d[key] = OutreachStatus(cleaned) if cleaned in OutreachStatus.__members__ else OutreachStatus.NOT_STARTED
            else:
                d[key] = str(val).strip() if val is not None else ""
        return cls(**d)
