"""
Transparent relevance scoring engine for internship lead prioritization.
Calculates explainable 0-100 scores based on technical alignment, project relevance,
role authority, email verification status, and personalization signals.
"""

from __future__ import annotations

import re
from typing import Tuple
from models import Lead, VerificationStatus


class RelevanceScorer:
    """Calculates deterministic, transparent relevance scores and explainable rationale."""

    def score_lead(self, lead: Lead) -> Tuple[int, str]:
        """
        Calculates a score between 0 and 100 with a detailed human-readable breakdown:
        1. Technical Domain Alignment (max 30 pts)
        2. Relevance to Existing Projects (Intelligent Video Analytics, CV) (max 20 pts)
        3. Decision-Maker Seniority (max 20 pts)
        4. Email Verification Status (max 15 pts)
        5. Verified Personalization Fact (max 10 pts)
        6. Hiring / Internship Activity (max 5 pts)
        """
        breakdown = []
        score = 0
        combined_text = f"{lead.company} {lead.description} {lead.industry} {lead.notes}".lower()

        # 1. Technical Domain Alignment (max 30 pts)
        if any(w in combined_text for w in ["video analytics", "computer vision", "camera stream", "vision"]):
            score += 30
            breakdown.append("+30 Tech: Computer Vision & Video Analytics")
        elif any(w in combined_text for w in ["generative ai", "llm", "foundation model", "avatar", "conversational"]):
            score += 25
            breakdown.append("+25 Tech: Generative AI / Foundation Models")
        elif any(w in combined_text for w in ["robotics", "visual cognition", "manipulation"]):
            score += 22
            breakdown.append("+22 Tech: Robotics & Industrial AI")
        elif any(w in combined_text for w in ["machine learning", "deep learning", "ai", "artificial intelligence"]):
            score += 20
            breakdown.append("+20 Tech: AI & Machine Learning")
        elif any(w in combined_text for w in ["opentelemetry", "kubernetes", "backend", "devops", "observability"]):
            score += 18
            breakdown.append("+18 Tech: Developer Tools & Backend Systems")
        else:
            score += 10
            breakdown.append("+10 Tech: General Software Engineering")

        # 2. Relevance to Sourasish's Confirmed Projects (max 20 pts)
        # Sourasish's primary project: Intelligent Video Analytics Platform
        if any(w in combined_text for w in ["video", "camera", "stream", "real-time vision", "surveillance", "opencv"]):
            score += 20
            breakdown.append("+20 Project Match: Direct Intelligent Video Analytics alignment")
        elif any(w in combined_text for w in ["deep learning", "computer vision", "neural", "vision model"]):
            score += 15
            breakdown.append("+15 Project Match: Deep learning & computer vision models")
        elif any(w in combined_text for w in ["backend", "python", "full-stack", "data pipeline"]):
            score += 10
            breakdown.append("+10 Project Match: Python backend & full-stack development")
        else:
            score += 5
            breakdown.append("+5 Project Match: General software prototype building")

        # 3. Decision-Maker Seniority (max 20 pts)
        role = (lead.designation or "").lower()
        if re.search(r"\b(cto|chief technology officer|technical director)\b", role):
            score += 20
            breakdown.append("+20 Role: CTO / Technical Director")
        elif re.search(r"\b(head of ai|ai lead|head of ml|director of ai)\b", role):
            score += 19
            breakdown.append("+19 Role: AI/ML Research Lead")
        elif re.search(r"\b(head of engineering|vp engineering|director of engineering)\b", role):
            score += 18
            breakdown.append("+18 Role: Head of Engineering")
        elif re.search(r"\b(co-founder|founder|ceo)\b", role):
            score += 16
            breakdown.append("+16 Role: Founder / CEO")
        elif re.search(r"\b(engineering manager|staff engineer|lead)\b", role):
            score += 14
            breakdown.append("+14 Role: Engineering Manager / Lead")
        elif re.search(r"\b(recruiter|talent|hr)\b", role):
            score += 10
            breakdown.append("+10 Role: Technical Recruiter")
        elif lead.person_name:
            score += 5
            breakdown.append("+5 Role: Contact identified without formal title")
        else:
            breakdown.append("+0 Role: No contact identified")

        # 4. Email Deliverability & Verification (max 15 pts)
        if lead.verification_status == VerificationStatus.VERIFIED:
            score += 15
            breakdown.append("+15 Email: Deliverable & VERIFIED")
        elif lead.verification_status == VerificationStatus.UNVERIFIED and lead.email:
            score += 7
            breakdown.append("+7 Email: Present but UNVERIFIED")
        elif lead.verification_status == VerificationStatus.INVALID:
            score += 0
            breakdown.append("+0 Email: INVALID syntax or domain")
        else:
            score += 0
            breakdown.append("+0 Email: MISSING email address")

        # 5. Verified Personalization Fact (max 10 pts)
        if lead.personalization_fact:
            score += 10
            breakdown.append("+10 Fact: Dedicated sourced personalization fact available")
        elif lead.description and len(lead.description) > 20:
            score += 6
            breakdown.append("+6 Fact: Company product description available")
        else:
            breakdown.append("+0 Fact: Minimal company product information")

        # 6. Hiring / Internship Signals (max 5 pts)
        if "careers or hiring section detected" in (lead.notes or "").lower():
            score += 5
            breakdown.append("+5 Hiring: Public hiring / careers section detected")
        else:
            score += 2
            breakdown.append("+2 Inquiry: Polite exploratory inquiry (no advertised vacancy)")

        score = min(max(score, 0), 100)
        reason = " | ".join(breakdown)

        lead.relevance_score = score
        lead.relevance_reason = reason
        return score, reason


relevance_scorer = RelevanceScorer()
