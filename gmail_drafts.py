"""
Gmail draft creation module with narrow OAuth permissions, idempotent tracking,
and multi-point safety approval gates. Strictly creates drafts; never sends emails.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import config
from database import db
from logging_config import logger
from models import ApprovalStatus, Lead, OutreachStatus, VerificationStatus
from sheets_store import sheets_store

# Google OAuth & Gmail API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False


class GmailDraftManager:
    """Manages Gmail OAuth 2.0 authentication and safe draft creation with strict gates."""

    # Narrowest practical permission: only composing drafts
    SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

    def __init__(
        self,
        client_secret_file: Optional[str] = None,
        token_file: Optional[str] = None,
        dry_run: Optional[bool] = None,
        db_instance: Optional[Any] = None,
    ):
        self.client_secret_file = client_secret_file or config.client_secret_file
        self.token_file = token_file or config.gmail_token_file
        self.dry_run = dry_run if dry_run is not None else config.dry_run
        self.db = db_instance or db
        self._service: Optional[Resource] = None

    def get_service(self) -> Optional[Resource]:
        """Authenticates via OAuth 2.0 and returns the Gmail API Resource."""
        if not GMAIL_API_AVAILABLE:
            logger.error("googleapiclient or google-auth-oauthlib is not installed.")
            return None

        if self._service:
            return self._service

        creds = None
        token_path = Path(self.token_file)

        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)
            except Exception as e:
                logger.warning("Could not read token file %s: %s", self.token_file, e)

        # Refresh or prompt for login
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.info("Refreshing expired Gmail OAuth token...")
                    creds.refresh(Request())
                    with open(token_path, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                except Exception as e:
                    logger.error("Failed to refresh OAuth token: %s", e)
                    creds = None

            if not creds:
                secret_path = Path(self.client_secret_file)
                if not secret_path.exists():
                    logger.info(
                        "Gmail OAuth credentials file not found (%s). Draft creation requires credentials.json.",
                        self.client_secret_file,
                    )
                    return None

                try:
                    logger.info("Initiating local OAuth consent flow for Gmail compose...")
                    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), self.SCOPES)
                    creds = flow.run_local_server(port=0)
                    with open(token_path, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                    logger.info("Saved fresh Gmail OAuth token to %s", self.token_file)
                except Exception as e:
                    logger.error("Gmail OAuth flow failed: %s", e)
                    return None

        try:
            self._service = build("gmail", "v1", credentials=creds)
            return self._service
        except Exception as e:
            logger.error("Failed to build Gmail service: %s", e)
            return None

    def validate_safety_gates(self, lead: Lead) -> Tuple[bool, str]:
        """
        Enforce strict safety gates before any draft is created:
        1. Lead must be explicitly marked APPROVED.
        2. Email must be present and marked VERIFIED.
        3. Recipient, subject, and body must be nonempty.
        4. Recipient must not be opted out.
        5. Lead must not already have been contacted or marked SENT.
        6. Lead must not already have a created draft (idempotency guard).
        """
        # Gate 1: Approval status
        if lead.approval_status != ApprovalStatus.APPROVED:
            return False, f"Gate Rejected: Approval status is '{lead.approval_status.value}' (Must be APPROVED)."

        # Gate 2: Email verification status
        if lead.verification_status != VerificationStatus.VERIFIED:
            return False, f"Gate Rejected: Email status is '{lead.verification_status.value}' (Only VERIFIED permitted)."

        # Gate 3: Required fields nonempty
        if not lead.email or not lead.email.strip():
            return False, "Gate Rejected: Recipient email is empty."
        if not lead.subject or not lead.subject.strip():
            return False, "Gate Rejected: Subject line is empty."
        if not lead.email_body or not lead.email_body.strip():
            return False, "Gate Rejected: Email body is empty."

        # Gate 4: Opt-out suppression
        if lead.opt_out or self.db.is_opted_out(lead.email, lead.domain):
            return False, "Gate Rejected: Recipient or domain is on the opt-out list."

        # Gate 5: Prior outreach status
        if lead.outreach_status == OutreachStatus.SENT:
            return False, "Gate Rejected: Lead is marked as already SENT."

        # Gate 6: Idempotency check (no duplicate drafts)
        if lead.gmail_draft_id:
            return False, f"Gate Rejected: Lead already has a draft ID: {lead.gmail_draft_id}."
        if self.db.has_draft_created(lead.lead_id):
            return False, f"Gate Rejected: SQLite already contains a recorded draft for {lead.lead_id}."

        return True, "All safety approval gates passed successfully."

    def build_message_payload(self, to_email: str, subject: str, body: str) -> Dict[str, Any]:
        """Build RFC 2822 base64url encoded message payload for Gmail API drafts."""
        message = EmailMessage()
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        raw_bytes = message.as_bytes()
        encoded_raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
        return {"message": {"raw": encoded_raw}}

    def create_single_draft(self, lead: Lead, dry_run: Optional[bool] = None) -> Tuple[bool, str, Optional[str]]:
        """
        Validates safety gates and creates a Gmail draft for a single lead.
        Returns: (success: bool, message: str, draft_id: Optional[str])
        """
        is_dry_run = self.dry_run if dry_run is None else dry_run

        # Step 1: Validate all safety gates
        passed, gate_message = self.validate_safety_gates(lead)
        if not passed:
            logger.warning("Safety gate blocked draft for %s (%s): %s", lead.company, lead.email, gate_message)
            return False, gate_message, None

        # Step 2: Handle dry run mode
        if is_dry_run:
            simulated_id = f"draft_simulated_{lead.lead_id}"
            logger.info("[DRY RUN] Would create Gmail draft for %s <%s>", lead.company, lead.email)
            return True, f"[DRY RUN] Draft creation validated successfully (Subject: '{lead.subject[:35]}...')", simulated_id

        # Step 3: Connect to Gmail service
        service = self.get_service()
        if not service:
            err = "Gmail API service unavailable (OAuth credentials missing or unauthorized)."
            logger.error(err)
            return False, err, None

        # Step 4: Call Gmail API drafts.create
        try:
            payload = self.build_message_payload(lead.email, lead.subject, lead.email_body)
            draft_resp = service.users().drafts().create(userId="me", body=payload).execute()
            gmail_draft_id = draft_resp.get("id")

            if not gmail_draft_id:
                return False, "Gmail API returned empty draft ID.", None

            # Step 5: Save draft record to SQLite immediately for crash recovery / idempotency
            self.db.record_draft_creation(
                lead_id=lead.lead_id,
                gmail_draft_id=gmail_draft_id,
                email=lead.email,
                subject=lead.subject,
            )

            # Update lead in-memory
            lead.gmail_draft_id = gmail_draft_id
            lead.outreach_status = OutreachStatus.DRAFT_CREATED

            # Step 6: Sync updated lead to Google Sheets or local CSV
            sheets_store.sync_lead(lead)
            sheets_store.log_event("DRAFT_CREATED", lead.lead_id, f"Created draft {gmail_draft_id} for {lead.email}")

            logger.info("Successfully created Gmail draft %s for %s (%s)", gmail_draft_id, lead.company, lead.email)
            return True, f"Created Gmail draft successfully (ID: {gmail_draft_id})", gmail_draft_id

        except Exception as e:
            err_msg = f"Failed to create Gmail draft via API: {e}"
            logger.error(err_msg)
            return False, err_msg, None

    def process_approved_batch(self, leads: List[Lead], dry_run: Optional[bool] = None) -> Dict[str, Any]:
        """
        Process a batch of leads, creating drafts only for those passing all safety gates.
        """
        summary = {
            "total_submitted": len(leads),
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "details": [],
        }

        for lead in leads:
            success, msg, draft_id = self.create_single_draft(lead, dry_run=dry_run)
            if success:
                summary["created"] += 1
                summary["details"].append({"lead_id": lead.lead_id, "status": "CREATED", "draft_id": draft_id, "message": msg})
            elif "Gate Rejected" in msg:
                summary["skipped"] += 1
                summary["details"].append({"lead_id": lead.lead_id, "status": "SKIPPED", "draft_id": None, "message": msg})
            else:
                summary["failed"] += 1
                summary["details"].append({"lead_id": lead.lead_id, "status": "FAILED", "draft_id": None, "message": msg})

        logger.info(
            "Batch draft processing complete: %d created, %d skipped, %d failed",
            summary["created"], summary["skipped"], summary["failed"]
        )
        return summary


gmail_manager = GmailDraftManager()
