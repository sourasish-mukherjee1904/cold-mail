"""
Company enrichment module.
Extracts domains, inspects official website metadata safely, detects technical areas,
and records verifiable source URLs without fabricating information.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional
import requests

from logging_config import logger
from models import Lead, normalize_domain

# High-priority technical focus keywords aligned with Sourasish's background
TECH_KEYWORDS = {
    "Computer Vision & Video Analytics": [
        "computer vision", "video analytics", "video stream", "camera", "object detection",
        "surveillance", "opencv", "cctv", "image processing", "facial recognition"
    ],
    "Generative AI & LLMs": [
        "generative ai", "llm", "large language model", "foundation model", "avatar",
        "conversational ai", "voice ai", "diffusion", "rag"
    ],
    "Robotics & Industrial AI": [
        "robotics", "manipulation", "visual cognition", "autonomous", "warehouse", "drone"
    ],
    "Developer Tools & SaaS": [
        "opentelemetry", "kubernetes", "observability", "ci/cd", "devops", "cloud", "developer tool"
    ],
    "AI & Machine Learning": [
        "machine learning", "deep learning", "neural network", "predictive model", "data science"
    ]
}


class CompanyEnricher:
    """Enriches company information with verified website metadata and technical tags."""

    def __init__(self, request_timeout: int = 5):
        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; WinterInternshipResearch/1.0; +https://github.com/sourasish)"
        })

    def enrich_lead(self, lead: Lead, fetch_live: bool = False) -> Lead:
        """
        Enrich a lead with normalized domain, detected technical focus, and verified website metadata.
        If fetch_live is True, safely fetches official homepage metadata.
        """
        # Ensure domain is normalized
        if not lead.domain and lead.website:
            lead.domain = normalize_domain(lead.website)
        elif not lead.website and lead.domain:
            lead.website = f"https://{lead.domain}"

        # If live fetching requested and website exists
        if fetch_live and lead.website:
            self._fetch_website_metadata(lead)

        # Detect technical tags from description and existing facts
        self._tag_technical_focus(lead)

        return lead

    def _fetch_website_metadata(self, lead: Lead) -> None:
        """Fetch title and meta description from official company website safely."""
        target_url = lead.website if lead.website.startswith("http") else f"https://{lead.website}"
        today_str = datetime.date.today().isoformat()

        try:
            resp = self.session.get(target_url, timeout=self.request_timeout, allow_redirects=True)
            if resp.status_code == 200:
                html = resp.text[:100000]  # First 100KB is plenty for head tags

                # Extract <title>
                title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                site_title = title_match.group(1).strip() if title_match else ""

                # Extract meta description
                desc_match = re.search(
                    r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
                    html,
                    re.IGNORECASE,
                ) or re.search(
                    r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']',
                    html,
                    re.IGNORECASE,
                )

                meta_desc = desc_match.group(1).strip() if desc_match else ""

                if meta_desc and not lead.description:
                    lead.description = meta_desc
                    lead.company_source = target_url
                    lead.source_date = today_str
                elif site_title and not lead.description:
                    lead.description = site_title
                    lead.company_source = target_url
                    lead.source_date = today_str

                # Detect careers / hiring mentions
                if re.search(r"\b(internship|intern|careers|hiring|join our team)\b", html, re.IGNORECASE):
                    note_tag = "Careers or hiring section detected on homepage."
                    if note_tag not in lead.notes:
                        lead.notes = f"{lead.notes} | {note_tag}".strip(" |")

                logger.info("Enriched %s metadata from %s", lead.company, target_url)
            else:
                logger.warning(
                    "Website returned HTTP %d for %s (%s)",
                    resp.status_code, lead.company, target_url
                )
        except requests.exceptions.Timeout:
            logger.warning("Timeout connecting to website for %s (%s)", lead.company, target_url)
        except requests.exceptions.RequestException as e:
            logger.warning("Network error fetching website for %s: %s", lead.company, e)
        except Exception as e:
            logger.error("Unexpected error enriching %s: %s", lead.company, e)

    def _tag_technical_focus(self, lead: Lead) -> None:
        """Classify and tag relevant technical domains based on company text."""
        combined_text = f"{lead.company} {lead.description} {lead.industry} {lead.notes}".lower()
        detected_categories = []

        for category, keywords in TECH_KEYWORDS.items():
            for kw in keywords:
                if kw in combined_text:
                    detected_categories.append(category)
                    break

        if detected_categories:
            if not lead.industry or lead.industry == "Technology":
                lead.industry = detected_categories[0]


company_enricher = CompanyEnricher()
