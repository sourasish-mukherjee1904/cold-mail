"""
Unit tests for lead deduplication, manual edit preservation, opt-out suppression, and CSV import/export.
"""

import csv
import os
import tempfile
import pytest
from database import Database
from models import (
    ApprovalStatus,
    Lead,
    OutreachStatus,
    SHEET_HEADERS,
    VerificationStatus,
)


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path=db_path)
    yield db
    if os.path.exists(db_path):
        os.remove(db_path)


def test_lead_initialization_and_normalization():
    lead = Lead(
        company="Test Corp",
        website="https://www.testcorp.ai/about?ref=123",
        email="  CONTACT@TestCorp.AI  ",
    )
    assert lead.domain == "testcorp.ai"
    assert lead.email == "contact@testcorp.ai"
    assert lead.lead_id.startswith("lead_")
    assert lead.verification_status == VerificationStatus.UNVERIFIED


def test_exact_29_columns_serialization():
    lead = Lead(
        company="AI Vision Ltd",
        website="https://aivision.in",
        email="hello@aivision.in",
        verification_status=VerificationStatus.VERIFIED,
        notes="High priority contact",
    )
    row = lead.to_sheet_row()
    assert len(row) == 29
    assert len(SHEET_HEADERS) == 29
    assert row[0] == lead.lead_id
    assert row[1] == "AI Vision Ltd"
    assert row[3] == "aivision.in"
    assert row[13] == "hello@aivision.in"
    assert row[15] == "VERIFIED"
    assert row[28] == "High priority contact"

    # Test round-trip reconstruction from sheet row
    reconstructed = Lead.from_sheet_row(row)
    assert reconstructed.lead_id == lead.lead_id
    assert reconstructed.company == lead.company
    assert reconstructed.domain == lead.domain
    assert reconstructed.email == lead.email
    assert reconstructed.verification_status == VerificationStatus.VERIFIED
    assert reconstructed.notes == "High priority contact"


def test_deduplication_by_email(temp_db):
    lead1 = Lead(
        company="Staqu Tech",
        website="https://staqu.com",
        person_name="Atul Rai",
        email="atul@staqu.com",
        notes="Initial note",
        approval_status=ApprovalStatus.APPROVED,
    )
    saved1, is_new1 = temp_db.upsert_lead(lead1)
    assert is_new1 is True

    # Re-inserting the same person with the same email
    lead2 = Lead(
        company="Staqu Technologies",
        website="https://staqu.com",
        person_name="Atul Rai",
        email="atul@staqu.com",
        notes="",  # Empty note in update should NOT wipe existing note
        approval_status=ApprovalStatus.PENDING,  # PENDING should NOT overwrite APPROVED
    )
    saved2, is_new2 = temp_db.upsert_lead(lead2)
    assert is_new2 is False
    assert saved2.lead_id == saved1.lead_id

    # Retrieve from DB to verify preservation
    retrieved = temp_db.get_lead(saved1.lead_id)
    assert retrieved is not None
    assert retrieved.notes == "Initial note"
    assert retrieved.approval_status == ApprovalStatus.APPROVED


def test_deduplication_by_domain_and_person(temp_db):
    lead1 = Lead(
        company="DaveAI",
        website="https://iamdave.ai",
        person_name="Sriram P H",
        designation="CEO",
    )
    saved1, is_new1 = temp_db.upsert_lead(lead1)
    assert is_new1 is True

    # Same domain and person name, but newly found email
    lead2 = Lead(
        company="DaveAI Inc",
        website="https://iamdave.ai",
        person_name="Sriram P H",
        designation="Co-Founder & CEO",
        email="sriram@iamdave.ai",
    )
    saved2, is_new2 = temp_db.upsert_lead(lead2)
    assert is_new2 is False
    assert saved2.lead_id == saved1.lead_id


def test_opt_out_suppression(temp_db):
    temp_db.add_opt_out(email="stop@company.com", domain="blockme.ai", reason="Unsubscribe request")

    assert temp_db.is_opted_out(email="stop@company.com") is True
    assert temp_db.is_opted_out(domain="blockme.ai") is True
    assert temp_db.is_opted_out(email="safe@other.com", domain="other.com") is False

    # When inserting a lead that is opted out, lead.opt_out should become True
    opted_lead = Lead(
        company="Block Me",
        website="https://blockme.ai",
        email="hr@blockme.ai",
    )
    saved, _ = temp_db.upsert_lead(opted_lead)
    assert saved.opt_out is True
    assert saved.outreach_status == OutreachStatus.OPTED_OUT


def test_csv_import_and_export(temp_db):
    # Import the sample leads CSV
    sample_csv = os.path.join(os.path.dirname(__file__), "..", "data", "sample_leads.csv")
    new_count, updated_count = temp_db.import_from_csv(sample_csv)
    assert new_count == 3
    assert updated_count == 0

    # Re-importing should result in 0 new and 3 updated
    new_count2, updated_count2 = temp_db.import_from_csv(sample_csv)
    assert new_count2 == 0
    assert updated_count2 == 3

    # Export to a temp CSV
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        export_path = f.name

    try:
        temp_db.export_to_csv(export_path)
        assert os.path.exists(export_path)
        with open(export_path, "r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
            assert len(reader) == 4  # Header + 3 leads
            assert reader[0][0] == "lead_id"
            assert reader[1][1] in ["Staqu Technologies", "DaveAI", "Wadhwani AI"]
    finally:
        if os.path.exists(export_path):
            os.remove(export_path)
