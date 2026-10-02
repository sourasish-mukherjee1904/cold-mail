"""
Unit tests for relevance scoring, explainability, deterministic personalization, and word limits.
"""

import pytest
from models import Lead, VerificationStatus
from personalization import EmailGenerator, extract_first_name
from relevance import RelevanceScorer


def test_extract_first_name():
    assert extract_first_name("Atul Rai") == "Atul"
    assert extract_first_name("Dr. Alpan Raval") == "Alpan"
    assert extract_first_name("Mr. Sriram P H") == "Sriram"
    assert extract_first_name("") == ""


def test_relevance_scoring_cv_video_analytics():
    scorer = RelevanceScorer()
    lead = Lead(
        company="Staqu Technologies",
        website="https://staqu.com",
        description="Jarvis video analytics platform for camera stream surveillance and security.",
        industry="Computer Vision / Video Analytics",
        person_name="Atul Rai",
        designation="Co-Founder & CEO",
        email="atul@staqu.com",
        verification_status=VerificationStatus.VERIFIED,
        personalization_fact="Staqu builds Jarvis video analytics for real-time camera streams.",
    )

    score, reason = scorer.score_lead(lead)
    assert 85 <= score <= 100
    assert "+30 Tech: Computer Vision & Video Analytics" in reason
    assert "+20 Project Match: Direct Intelligent Video Analytics alignment" in reason
    assert "+15 Email: Deliverable & VERIFIED" in reason
    assert "+16 Role: Founder / CEO" in reason


def test_relevance_scoring_missing_fields_penalty():
    scorer = RelevanceScorer()
    # Bare minimum lead with no email and unknown role
    lead = Lead(
        company="Unknown AI Startup",
        website="https://unknown.ai",
        description="Generic tech company.",
    )

    score, reason = scorer.score_lead(lead)
    assert score < 50
    assert "+0 Email: MISSING email address" in reason
    assert "+0 Role: No contact identified" in reason


def test_email_generation_cv_platform_connection():
    generator = EmailGenerator()
    lead = Lead(
        company="Detect Technologies",
        website="https://detecttechnologies.com",
        description="Industrial computer vision and drone video stream analytics.",
        industry="Computer Vision / Video Analytics",
        person_name="Daniel Raj David",
        designation="Co-Founder & CEO",
        email="daniel@detecttechnologies.com",
        verification_status=VerificationStatus.VERIFIED,
        personalization_fact="Detect Technologies builds industrial AI for real-time video stream hazard detection.",
    )

    subject, body = generator.generate_email_content(lead)

    # Subject line check
    assert "Winter 2026 Internship Inquiry" in subject
    assert "Computer Vision & Video Analytics" in subject
    assert "Sourasish Mukherjee" in subject

    # Body check
    assert "Dear Daniel," in body
    assert "IIT Kharagpur" in body
    assert "intelligent video analytics platform" in body
    assert "Detect Technologies" in body
    assert "https://github.com/sourasish" in body
    # Ensure word count is concise
    words = body.split()
    assert len(words) <= 170


def test_email_generation_truthfulness_and_no_hallucination():
    generator = EmailGenerator()
    # Generic lead without existing relationship or vacancy
    lead = Lead(
        company="Sarvam AI",
        description="Developing Indic voice and foundation language models.",
        person_name="Pratyush Kumar",
        designation="Co-Founder",
        email="contact@sarvam.ai",
    )

    subject, body = generator.generate_email_content(lead)

    # Must NOT claim an open internship vacancy exists
    assert "hiring for" not in body.lower()
    # Must describe as exploratory
    assert "explore potential winter internship opportunities" in body.lower()
    # Must maintain Sourasish's truthful IIT Kharagpur details
    assert "Sourasish Mukherjee" in body
    assert "IIT Kharagpur" in body
