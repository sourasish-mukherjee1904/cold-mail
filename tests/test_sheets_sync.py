"""
Unit tests for Google Sheets store, offline CSV fallback, and retry mechanism.
Uses mocks to avoid external network/Google API dependencies during testing.
"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from database import Database
from models import ApprovalStatus, Lead, SHEET_HEADERS, VerificationStatus
from sheets_store import SheetsStore, retry_with_backoff


def test_offline_csv_mode_fallback():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f_csv, \
         tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f_db:
        csv_path = f_csv.name
        db_path = f_db.name

    try:
        isolated_db = Database(db_path=db_path)
        store = SheetsStore(
            spreadsheet_id=None,
            service_account_file="non_existent_creds.json",
            csv_fallback_path=csv_path,
            db_instance=isolated_db,
        )
        assert store.is_offline is True

        lead = Lead(
            company="Vision Labs India",
            website="https://visionlabs.in",
            email="contact@visionlabs.in",
            verification_status=VerificationStatus.VERIFIED,
            notes="Manually added test lead",
        )

        success, is_new = store.sync_lead(lead)
        assert success is True
        assert is_new is True

        # Check that CSV file was created with headers and lead
        assert os.path.exists(csv_path)
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            assert len(lines) >= 2
            assert lines[0] == ",".join(SHEET_HEADERS)
            assert "Vision Labs India" in lines[1]
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)
        if os.path.exists(db_path):
            os.remove(db_path)


def test_mocked_google_sheets_sync(mocker):
    # Mock gspread client and spreadsheet
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = SHEET_HEADERS
    mock_worksheet.col_values.return_value = ["lead_id", "lead_test123"]
    mock_worksheet.get_all_values.return_value = [SHEET_HEADERS]

    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    store = SheetsStore(spreadsheet_id="dummy_sheet_id", service_account_file="dummy.json")
    store.client = mock_client
    store.spreadsheet = mock_spreadsheet
    store.leads_worksheet = mock_worksheet
    store.is_offline = False

    # Sync an updated lead
    lead = Lead(
        lead_id="lead_test123",
        company="Staqu Tech",
        website="https://staqu.com",
        email="atul@staqu.com",
        verification_status=VerificationStatus.VERIFIED,
    )

    success, is_new = store.sync_lead(lead)
    assert success is True
    # Row 2 should be updated
    mock_worksheet.update.assert_called_once()
    args, kwargs = mock_worksheet.update.call_args
    assert args[0] == "A2:AC2"
    assert args[1][0][0] == "lead_test123"


def test_retry_with_backoff_transient_failure():
    attempts = 0

    @retry_with_backoff(max_retries=3, initial_delay=0.01, backoff_factor=1.5)
    def flaky_api_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception("HTTP 429 Quota Exceeded Rate Limit")
        return "SUCCESS"

    result = flaky_api_call()
    assert result == "SUCCESS"
    assert attempts == 3
