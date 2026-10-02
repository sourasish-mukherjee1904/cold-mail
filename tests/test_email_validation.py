"""
Unit tests for contact discovery, role scoring, email validation, Hunter API mocks, and fallbacks.
"""

import pytest
from unittest.mock import MagicMock, patch

from contact_discovery import ContactDiscovery, score_role_priority
from email_verification import EmailVerifier, HunterClient
from models import Lead, VerificationStatus


def test_score_role_priority():
    score_cto, label_cto = score_role_priority("Chief Technology Officer")
    assert score_cto == 100
    assert "CTO" in label_cto

    score_ai, label_ai = score_role_priority("Head of AI & ML Research")
    assert score_ai == 95

    score_ceo, label_ceo = score_role_priority("Co-Founder & CEO")
    assert score_ceo == 85

    score_recruiter, label_recruiter = score_role_priority("Technical Recruiter")
    assert score_recruiter == 60


def test_contact_assignment():
    discovery = ContactDiscovery()
    lead = Lead(company="Detect Tech", website="https://detecttechnologies.com")

    updated = discovery.assign_contact(
        lead=lead,
        name="Daniel Raj David",
        designation="Co-Founder & CEO",
        profile_url="https://detecttechnologies.com/team",
        email="daniel@detecttechnologies.com",
        source_url="https://detecttechnologies.com/contact",
        is_verified=True,
    )

    assert updated.person_name == "Daniel Raj David"
    assert updated.designation == "Co-Founder & CEO"
    assert updated.email == "daniel@detecttechnologies.com"
    assert updated.verification_status == VerificationStatus.VERIFIED
    assert updated.company_source == "https://detecttechnologies.com/contact"


def test_email_syntax_and_disposable_filtering():
    verifier = EmailVerifier()

    assert verifier.validate_syntax("atul.rai@staqu.com") is True
    assert verifier.validate_syntax("sriram@iamdave.ai") is True
    assert verifier.validate_syntax("invalid-email-address") is False
    assert verifier.validate_syntax("test@mailinator.com") is False  # Disposable domain
    assert verifier.validate_syntax("test@tempmail.com") is False


def test_hunter_api_verification_mocked(mocker):
    # Case 1: Valid deliverable email
    mock_resp_valid = MagicMock()
    mock_resp_valid.status_code = 200
    mock_resp_valid.json.return_value = {
        "data": {
            "status": "valid",
            "score": 95,
            "email": "atul@staqu.com",
        }
    }

    mock_client = HunterClient(api_key="mock_key_12345")
    verifier = EmailVerifier(hunter_client=mock_client)

    with patch.object(mock_client.session, "get", return_value=mock_resp_valid):
        lead = Lead(company="Staqu Tech", email="atul@staqu.com")
        verified_lead = verifier.verify_lead_email(lead)
        assert verified_lead.verification_status == VerificationStatus.VERIFIED
        assert "Hunter verified" in verified_lead.email_source

    # Case 2: Accept-all or unknown email (Must NEVER be marked VERIFIED)
    mock_resp_accept_all = MagicMock()
    mock_resp_accept_all.status_code = 200
    mock_resp_accept_all.json.return_value = {
        "data": {
            "status": "accept_all",
            "score": 55,
            "email": "info@staqu.com",
        }
    }

    with patch.object(mock_client.session, "get", return_value=mock_resp_accept_all):
        lead2 = Lead(company="Staqu Tech", email="info@staqu.com")
        verified_lead2 = verifier.verify_lead_email(lead2)
        assert verified_lead2.verification_status == VerificationStatus.UNVERIFIED


def test_hunter_api_error_handling_mocked():
    mock_client = HunterClient(api_key="mock_key_12345")
    verifier = EmailVerifier(hunter_client=mock_client)

    # 429 Quota Exceeded
    mock_429 = MagicMock()
    mock_429.status_code = 429
    with patch.object(mock_client.session, "get", return_value=mock_429):
        lead = Lead(company="DaveAI", email="info@iamdave.ai")
        # Should gracefully maintain UNVERIFIED without crashing
        verified = verifier.verify_lead_email(lead)
        assert verified.verification_status == VerificationStatus.UNVERIFIED

    # 401 Unauthorized (invalid key)
    mock_401 = MagicMock()
    mock_401.status_code = 401
    with patch.object(mock_client.session, "get", return_value=mock_401):
        lead2 = Lead(company="DaveAI", email="info@iamdave.ai")
        verified2 = verifier.verify_lead_email(lead2)
        assert verified2.verification_status == VerificationStatus.UNVERIFIED


def test_manual_email_fallback():
    verifier = EmailVerifier()
    lead = Lead(company="Manual Tech", website="https://manualtech.in")

    # Manually add verified contact email from official contact page
    verifier.record_manual_email(
        lead=lead,
        email="careers@manualtech.in",
        source_url="https://manualtech.in/contact-us",
        is_verified=True,
        notes="Confirmed from official website footer",
    )

    assert lead.email == "careers@manualtech.in"
    assert lead.verification_status == VerificationStatus.VERIFIED
    assert lead.email_source == "https://manualtech.in/contact-us"
    assert "Confirmed from official website footer" in lead.notes
