"""
Unit tests for Gmail API draft creation idempotency, SQLite recording, and restart recovery.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from database import Database
from gmail_drafts import GmailDraftManager
from models import ApprovalStatus, Lead, OutreachStatus, VerificationStatus


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    tdb = Database(db_path=path)
    yield tdb
    if os.path.exists(path):
        os.remove(path)


def test_gmail_draft_creation_and_recovery(mocker, temp_db):
    # Setup mock Gmail service
    mock_service = MagicMock()
    mock_drafts = MagicMock()
    mock_create = MagicMock()
    mock_create.execute.return_value = {"id": "gmail_draft_abc98765"}
    mock_drafts.create.return_value = mock_create
    mock_service.users.return_value.drafts.return_value = mock_drafts

    manager = GmailDraftManager(dry_run=False, db_instance=temp_db)
    manager._service = mock_service

    lead = Lead(
        lead_id="lead_staqu_recover_test",
        company="Staqu Tech",
        website="https://staqu.com",
        email="atul@staqu.com",
        subject="Internship Inquiry - Computer Vision",
        email_body="Dear Atul,\n\nI am writing to inquire...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.APPROVED,
    )

    # Initial draft creation
    success, msg, draft_id = manager.create_single_draft(lead, dry_run=False)
    assert success is True
    assert draft_id == "gmail_draft_abc98765"
    assert lead.gmail_draft_id == "gmail_draft_abc98765"
    assert lead.outreach_status == OutreachStatus.DRAFT_CREATED

    # Verify that the draft ID was immediately recorded in SQLite
    assert temp_db.has_draft_created("lead_staqu_recover_test") is True

    # Re-attempting draft creation (e.g. after restart or re-running script)
    # MUST be rejected by idempotency gate without invoking Gmail API again
    mock_create.reset_mock()
    success2, msg2, draft_id2 = manager.create_single_draft(lead, dry_run=False)
    assert success2 is False
    assert "already has a draft ID" in msg2 or "already contains a recorded draft" in msg2
    mock_create.execute.assert_not_called()


def test_batch_draft_processing_mixed_leads(mocker, temp_db):
    mock_service = MagicMock()
    mock_create = MagicMock()
    mock_create.execute.return_value = {"id": "batch_draft_111"}
    mock_service.users.return_value.drafts.return_value.create.return_value = mock_create

    manager = GmailDraftManager(dry_run=False, db_instance=temp_db)
    manager._service = mock_service

    lead_valid = Lead(
        lead_id="lead_batch_valid",
        company="Valid Tech",
        email="founder@valid.com",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.APPROVED,
    )

    lead_unapproved = Lead(
        lead_id="lead_batch_unapproved",
        company="Unapproved Tech",
        email="founder@unapproved.com",
        subject="Internship Inquiry",
        email_body="Hello...",
        verification_status=VerificationStatus.VERIFIED,
        approval_status=ApprovalStatus.PENDING,  # PENDING
    )

    leads = [lead_valid, lead_unapproved]
    summary = manager.process_approved_batch(leads, dry_run=False)

    assert summary["total_submitted"] == 2
    assert summary["created"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 0
