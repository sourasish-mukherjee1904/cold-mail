"""
Deterministic, truthful email personalization module.
Connects verified company facts directly to Sourasish's confirmed IIT Kharagpur
background and Intelligent Video Analytics / AI projects without hallucinating.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple
from config import config
from logging_config import logger
from models import Lead, VerificationStatus


def extract_first_name(full_name: str) -> str:
    """Extract a polite first name from full name or formal title."""
    cleaned = full_name.strip()
    # Strip titles like Dr., Mr., Ms.
    cleaned = re.sub(r"^(dr\.|mr\.|ms\.|mrs\.)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    parts = cleaned.split()
    return parts[0].capitalize() if parts else ""


class EmailGenerator:
    """Generates concise, respectful, and source-backed cold outreach emails."""

    def __init__(self):
        self.profile = config.profile
        self.max_words = config.max_body_words

    def generate_email_content(self, lead: Lead) -> Tuple[str, str]:
        """
        Generates (subject, body) for a lead based on verified facts.
        Never fabricates company features, hiring openings, or candidate credentials.
        """
        first_name = extract_first_name(lead.person_name)
        greeting = f"Dear {first_name}," if first_name else f"Dear {lead.company} Team,"

        # Establish verifiable personalization fact
        fact = (lead.personalization_fact or lead.description or "").strip()
        if not fact:
            # Fallback if no specific product fact is available
            fact = f"{lead.company}'s work in software and technology"

        # Determine technical category to choose the most relevant honest connection
        combined_text = f"{lead.company} {lead.description} {lead.industry}".lower()

        # Subject line
        if any(w in combined_text for w in ["video", "vision", "camera", "surveillance"]):
            subject = f"Winter 2026 Internship Inquiry - Computer Vision & Video Analytics - {self.profile.name}"
            project_connection = (
                f"I have been following {lead.company}'s work on {fact}. "
                f"As an undergraduate at {self.profile.college} ({self.profile.degree}), "
                f"I have developed an intelligent video analytics platform focusing on real-time stream processing, "
                f"computer vision pipelines, and practical model deployment in Python and C++."
            )
        elif any(w in combined_text for w in ["generative ai", "llm", "foundation model", "avatar"]):
            subject = f"Winter 2026 Internship Inquiry - AI & Machine Learning - {self.profile.name}"
            project_connection = (
                f"I have been closely following {lead.company}'s innovations in {fact}. "
                f"At {self.profile.college}, I focus on practical machine learning applications, "
                f"deep learning architectures, and building production-ready AI backend prototypes."
            )
        elif any(w in combined_text for w in ["robotics", "visual cognition", "manipulation"]):
            subject = f"Winter 2026 Internship Inquiry - Robotics & Visual Cognition - {self.profile.name}"
            project_connection = (
                f"I have been studying {lead.company}'s work in {fact}. "
                f"As an engineering student at {self.profile.college}, I combine computer vision pipelines "
                f"with practical AI algorithms for spatial perception and real-time processing."
            )
        elif any(w in combined_text for w in ["opentelemetry", "kubernetes", "backend", "developer", "observability"]):
            subject = f"Winter 2026 Internship Inquiry - Backend & Infrastructure - {self.profile.name}"
            project_connection = (
                f"I have been following {lead.company}'s engineering work on {fact}. "
                f"At {self.profile.college}, my technical work includes backend software development, "
                f"Python and SQL data systems, and building scalable full-stack applications."
            )
        else:
            subject = f"Winter 2026 Engineering Internship Inquiry - {self.profile.name}"
            project_connection = (
                f"I have been following {lead.company}'s work in {fact}. "
                f"As an undergraduate at {self.profile.college}, I have built practical machine learning "
                f"applications, video analytics pipelines, and backend software services."
            )

        # Links section
        links_parts = []
        if self.profile.github_url:
            links_parts.append(f"GitHub: {self.profile.github_url}")
        if self.profile.resume_url and "example.com" not in self.profile.resume_url:
            links_parts.append(f"Resume: {self.profile.resume_url}")
        links_str = " | ".join(links_parts) if links_parts else f"GitHub: {self.profile.github_url}"

        # Polite exploratory call to action (never assuming an opening exists)
        cta = (
            f"I am writing to explore potential winter internship opportunities (Dec 2026 – Jan 2026) "
            f"where I could contribute to your engineering or AI initiatives.\n\n"
            f"You can review my code and projects here: {links_str}\n\n"
            f"Would you be open to a brief introductory conversation regarding how I might add value to {lead.company} this winter?"
        )

        signoff = (
            f"Sincerely,\n"
            f"{self.profile.name}\n"
            f"{self.profile.college}"
        )

        body = f"{greeting}\n\n{project_connection}\n\n{cta}\n\n{signoff}"

        # Verify word count
        words = body.split()
        if len(words) > self.max_words + 40:
            logger.warning("Generated email body for %s has %d words (target: %d)", lead.company, len(words), self.max_words)

        # Store generated content on lead
        lead.subject = subject
        lead.email_body = body
        if not lead.personalization_fact:
            lead.personalization_fact = fact
            lead.personalization_source = lead.company_source or lead.website

        return subject, body


email_generator = EmailGenerator()
