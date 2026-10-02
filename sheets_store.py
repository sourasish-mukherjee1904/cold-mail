"""
Google Sheets storage integration using gspread with automatic schema initialization,
incremental synchronization, edit preservation, retry backoff, and offline CSV fallback.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import config
from database import db
from logging_config import logger
from models import SHEET_HEADERS, ApprovalStatus, Lead, OutreachStatus, VerificationStatus

# Optional imports for Google Cloud
try:
    import gspread
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials as UserCredentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False


def retry_with_backoff(max_retries: int = 3, initial_delay: float = 1.0, backoff_factor: float = 2.0):
    """Decorator for retry handling with exponential backoff on transient errors."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    err_msg = str(e).lower()
                    # Check for rate limit or server errors
                    if any(code in err_msg for code in ["429", "500", "502", "503", "quota", "temporarily"]):
                        logger.warning(
                            "Transient error calling %s (attempt %d/%d): %s. Retrying in %.1fs...",
                            func.__name__, attempt, max_retries, e, delay
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        raise
            logger.error("Function %s failed after %d retries: %s", func.__name__, max_retries, last_exception)
            raise last_exception
        return wrapper
    return decorator


class SheetsStore:
    """Manages reading and writing leads to Google Sheets or offline CSV."""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(
        self,
        spreadsheet_id: Optional[str] = None,
        service_account_file: Optional[str] = None,
        csv_fallback_path: Optional[str] = None,
        db_instance: Optional[Any] = None,
    ):
        self.spreadsheet_id = spreadsheet_id or config.spreadsheet_id
        self.service_account_file = service_account_file or config.service_account_file
        self.csv_fallback_path = csv_fallback_path or config.csv_data_path
        self.db = db_instance or db

        self.client: Optional[Any] = None
        self.spreadsheet: Optional[Any] = None
        self.leads_worksheet: Optional[Any] = None
        self.logs_worksheet: Optional[Any] = None
        self.is_offline = True

        self._initialize()

    def _initialize(self) -> None:
        """Attempt Google Sheets connection; if unavailable or missing, enable offline mode."""
        if not GSPREAD_AVAILABLE:
            logger.info("gspread not installed. Operating in Offline CSV Mode.")
            self.is_offline = True
            return

        sa_path = Path(self.service_account_file)
        if not sa_path.exists():
            logger.info(
                "Google Service Account file not found (%s). Operating in Offline CSV Mode.",
                self.service_account_file,
            )
            self.is_offline = True
            return

        try:
            creds = ServiceAccountCredentials.from_service_account_file(
                str(sa_path),
                scopes=self.SCOPES,
            )
            self.client = gspread.authorize(creds)
            self.is_offline = False
            logger.info("Authenticated with Google Sheets via Service Account.")
            self._setup_worksheets()
        except Exception as e:
            logger.warning("Failed to authenticate with Google Sheets: %s. Falling back to Offline CSV Mode.", e)
            self.is_offline = True

    @retry_with_backoff(max_retries=3)
    def _setup_worksheets(self) -> None:
        """Open or create spreadsheet and ensure exact 29-column header schema."""
        if self.is_offline or not self.client:
            return

        if self.spreadsheet_id:
            try:
                self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            except Exception as e:
                logger.error("Could not open spreadsheet by ID '%s': %s", self.spreadsheet_id, e)
                self.is_offline = True
                return
        else:
            try:
                self.spreadsheet = self.client.open(config.spreadsheet_title)
            except gspread.exceptions.SpreadsheetNotFound:
                logger.info("Creating new Google Spreadsheet: '%s'", config.spreadsheet_title)
                self.spreadsheet = self.client.create(config.spreadsheet_title)
                self.spreadsheet_id = self.spreadsheet.id
                logger.info("Created spreadsheet ID: %s", self.spreadsheet_id)

        # 1. Setup 'Leads' worksheet
        try:
            self.leads_worksheet = self.spreadsheet.worksheet(config.worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            logger.info("Creating worksheet '%s'", config.worksheet_name)
            self.leads_worksheet = self.spreadsheet.add_worksheet(
                title=config.worksheet_name,
                rows="100",
                cols=str(len(SHEET_HEADERS)),
            )

        # Inspect headers
        existing_headers = self.leads_worksheet.row_values(1)
        if not existing_headers:
            logger.info("Initializing 29-column headers in 'Leads' worksheet.")
            self.leads_worksheet.insert_row(SHEET_HEADERS, 1)
        else:
            # Check if columns match
            if existing_headers[:len(SHEET_HEADERS)] != SHEET_HEADERS:
                logger.warning(
                    "Worksheet headers differ from required schema. Overwriting row 1 with canonical 29 columns."
                )
                self.leads_worksheet.update("A1:AC1", [SHEET_HEADERS])

        # 2. Setup optional 'Logs' worksheet
        try:
            self.logs_worksheet = self.spreadsheet.worksheet("Logs")
        except gspread.exceptions.WorksheetNotFound:
            try:
                self.logs_worksheet = self.spreadsheet.add_worksheet(title="Logs", rows="200", cols="4")
                self.logs_worksheet.insert_row(["timestamp", "event_type", "lead_id", "message"], 1)
            except Exception as e:
                logger.warning("Could not initialize Logs worksheet: %s", e)

    @retry_with_backoff(max_retries=3)
    def read_all_leads(self) -> List[Lead]:
        """Read all leads from Google Sheets or the local CSV file."""
        if self.is_offline:
            logger.info("Reading leads from local CSV: %s", self.csv_fallback_path)
            self.db.import_from_csv(self.csv_fallback_path)
            return self.db.get_all_leads()

        if not self.leads_worksheet:
            return []

        rows = self.leads_worksheet.get_all_values()
        if len(rows) <= 1:
            return []

        leads = []
        for r in rows[1:]:
            if not r or not any(r):
                continue
            try:
                lead = Lead.from_sheet_row(r)
                self.db.upsert_lead(lead)
                leads.append(lead)
            except Exception as e:
                logger.warning("Error parsing sheet row %s: %s", r[:3], e)

        logger.info("Read %d leads from Google Sheets.", len(leads))
        return leads

    @retry_with_backoff(max_retries=3)
    def sync_lead(self, lead: Lead) -> Tuple[bool, bool]:
        """
        Incrementally write or update a single lead.
        Returns (success: bool, is_new: bool).
        """
        # Save to local SQLite first
        saved_lead, is_new = self.db.upsert_lead(lead)

        if self.is_offline:
            # Sync to local CSV
            self.db.export_to_csv(self.csv_fallback_path)
            return True, is_new

        if not self.leads_worksheet:
            return False, is_new

        try:
            # Find row index by lead_id
            lead_id_col = self.leads_worksheet.col_values(1)
            row_idx = None
            if lead.lead_id in lead_id_col:
                row_idx = lead_id_col.index(lead.lead_id) + 1

            row_data = saved_lead.to_sheet_row()
            if row_idx:
                # Update existing row
                cell_range = f"A{row_idx}:AC{row_idx}"
                self.leads_worksheet.update(cell_range, [row_data])
                logger.info("Updated lead %s at row %d in Google Sheets", lead.lead_id, row_idx)
            else:
                # Append new row
                self.leads_worksheet.append_row(row_data)
                logger.info("Appended new lead %s (%s) to Google Sheets", lead.lead_id, lead.company)

            return True, is_new
        except Exception as e:
            logger.error("Failed to sync lead %s to Google Sheets: %s", lead.lead_id, e)
            return False, is_new

    @retry_with_backoff(max_retries=3)
    def sync_all_leads(self, leads: Optional[List[Lead]] = None) -> Dict[str, int]:
        """
        Batch synchronize leads to Google Sheets or local CSV.
        Preserves manual edits already on the sheet.
        """
        all_leads = leads or self.db.get_all_leads()
        stats = {"created": 0, "updated": 0, "total": len(all_leads)}

        if self.is_offline:
            self.db.export_to_csv(self.csv_fallback_path)
            stats["updated"] = len(all_leads)
            return stats

        if not self.leads_worksheet:
            return stats

        # Read existing sheet data to preserve manual edits
        existing_rows = self.leads_worksheet.get_all_values()
        existing_map: Dict[str, Tuple[int, Lead]] = {}

        if len(existing_rows) > 1:
            for idx, r in enumerate(existing_rows[1:], start=2):
                if r and r[0]:
                    try:
                        existing_lead = Lead.from_sheet_row(r)
                        existing_map[r[0]] = (idx, existing_lead)
                    except Exception:
                        pass

        rows_to_append = []
        updates_batch = []

        for lead in all_leads:
            if lead.lead_id in existing_map:
                row_idx, sheet_lead = existing_map[lead.lead_id]
                # Preserve manual edits from sheet if local was blank
                if sheet_lead.notes and not lead.notes:
                    lead.notes = sheet_lead.notes
                if sheet_lead.approval_status != ApprovalStatus.PENDING and lead.approval_status == ApprovalStatus.PENDING:
                    lead.approval_status = sheet_lead.approval_status
                if sheet_lead.gmail_draft_id and not lead.gmail_draft_id:
                    lead.gmail_draft_id = sheet_lead.gmail_draft_id

                # Save merged to db
                self.db.upsert_lead(lead)
                updates_batch.append({
                    "range": f"A{row_idx}:AC{row_idx}",
                    "values": [lead.to_sheet_row()],
                })
                stats["updated"] += 1
            else:
                saved_lead, _ = self.db.upsert_lead(lead)
                rows_to_append.append(saved_lead.to_sheet_row())
                stats["created"] += 1

        # Execute batch updates
        if updates_batch:
            self.leads_worksheet.batch_update(updates_batch)
            logger.info("Batch updated %d rows in Google Sheets", len(updates_batch))

        if rows_to_append:
            self.leads_worksheet.append_rows(rows_to_append)
            logger.info("Appended %d new rows to Google Sheets", len(rows_to_append))

        return stats

    def log_event(self, event_type: str, lead_id: str, message: str) -> None:
        """Write an operational event to Logs sheet or fallback to local logger."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info("[%s] [%s] %s: %s", timestamp, event_type, lead_id, message)
        if not self.is_offline and self.logs_worksheet:
            try:
                self.logs_worksheet.append_row([timestamp, event_type, lead_id, message])
            except Exception as e:
                logger.warning("Could not write to Logs sheet: %s", e)


sheets_store = SheetsStore()
