"""
Unit tests for Gmail draft safety approval gates and dry-run mode.
Ensures drafts are NEVER created unless all criteria pass without exception.
"""

import pytest
from database import Database
from gmail_drafts import GmailDraftManager
from models import ApprovalStatus, Lead, OutreachStatus, VerificationStatus


@pytest.fixture
def manager():
    return GmailDraftManager(dry_run=True)


def test_gate_rejects_pending_or_rejected(manager):
    lead_pending = Lead(
        company="Staqu Tech",
        email="atul@staqu.com",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.PENDING,  # PENDING
    )
    passed, msg = manager.validate_safety_gates(lead_pending)
    assert passed is False
    assert "Must be APPROVED" in msg

    lead_rejected = Lead(
        company="Staqu Tech",
        email="atul@staqu.com",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.REJECTED,  # REJECTED
    )
    passed, msg = manager.validate_safety_gates(lead_rejected)
    assert passed is False
    assert "Must be APPROVED" in msg


def test_gate_rejects_unverified_emails(manager):
    lead_unverified = Lead(
        company="DaveAI",
        email="info@iamdave.ai",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.UNVERIFIED,
        approval_status=ApprovalStatus.APPROVED,
    )
    passed, msg = manager.validate_safety_gates(lead_unverified)
    assert passed is False
    assert "Only VERIFIED permitted" in msg

    lead_invalid = Lead(
        company="DaveAI",
        email="bad-email",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.INVALID,
        approval_status=ApprovalStatus.APPROVED,
    )
    passed, msg = manager.validate_safety_gates(lead_invalid)
    assert passed is False
    assert "Only VERIFIED permitted" in msg


def test_gate_rejects_empty_content(manager):
    lead_no_subject = Lead(
        company="Detect Tech",
        email="daniel@detecttechnologies.com",
        subject="",  # Missing subject
        email_body="Hello...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.APPROVED,
    )
    passed, msg = manager.validate_safety_gates(lead_no_subject)
    assert passed is False
    assert "Subject line is empty" in msg


def test_gate_rejects_opted_out_recipients(manager):
    lead_opt_out = Lead(
        company="Block Corp",
        email="stop@blockcorp.com",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.APPROVED,
        opt_out=True,  # Opted out
    )
    passed, msg = manager.validate_safety_gates(lead_opt_out)
    assert passed is False
    assert "opt-out" in msg.lower()


def test_gate_rejects_already_sent_contacts(manager):
    lead_sent = Lead(
        company="Contacted Tech",
        email="hr@contacted.com",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.APPROVED,
        outreach_status=OutreachStatus.SENT,  # Already sent
    )
    passed, msg = manager.validate_safety_gates(lead_sent)
    assert passed is False
    assert "already SENT" in msg


def test_dry_run_draft_creation(manager):
    # Fully valid lead passing all gates
    lead_valid = Lead(
        company="CynLr",
        email="contact@cynlr.com",
        subject="Winter 2026 Internship Inquiry - Robotics & Visual Cognition",
        email_body="Dear Gokul,\n\nI have been following CynLr...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.APPROVED,
    )

    success, msg, draft_id = manager.create_single_draft(lead_valid, dry_run=True)
    assert success is True
    assert "[DRY RUN]" in msg
    assert draft_id.startswith("draft_simulated_")
