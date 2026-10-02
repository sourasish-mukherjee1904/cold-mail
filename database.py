"""
SQLite persistence, deduplication, caching, opt-out management, and draft idempotency.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import config
from logging_config import logger
from models import (
    ApprovalStatus,
    Lead,
    OutreachStatus,
    SHEET_HEADERS,
    VerificationStatus,
    normalize_domain,
    normalize_email,
)


class Database:
    """Manages the local SQLite database for caching, deduplication, and state tracking."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.sqlite_db_path
        self._ensure_db_dir()
        self.init_db()

    def _ensure_db_dir(self) -> None:
        db_file = Path(self.db_path)
        if db_file.parent and not db_file.parent.exists():
            db_file.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Returns SQLite connection with dict-like row access."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize database schema with robust indexes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Main leads table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    website TEXT,
                    domain TEXT,
                    description TEXT,
                    industry TEXT,
                    location TEXT,
                    company_size TEXT,
                    company_source TEXT,
                    source_date TEXT,
                    person_name TEXT,
                    designation TEXT,
                    professional_profile_url TEXT,
                    email TEXT,
                    email_source TEXT,
                    verification_status TEXT,
                    relevance_score INTEGER DEFAULT 0,
                    relevance_reason TEXT,
                    personalization_fact TEXT,
                    personalization_source TEXT,
                    subject TEXT,
                    email_body TEXT,
                    approval_status TEXT DEFAULT 'PENDING',
                    outreach_status TEXT DEFAULT 'NOT_STARTED',
                    gmail_draft_id TEXT,
                    last_contacted TEXT,
                    follow_up_date TEXT,
                    opt_out INTEGER DEFAULT 0,
                    notes TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                """
            )

            # Indexes for fast lookup & deduplication
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_approval ON leads(approval_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_outreach ON leads(outreach_status);")

            # Opt-out suppression table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS opt_outs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE,
                    domain TEXT,
                    reason TEXT,
                    opt_out_date TEXT
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_outs_email ON opt_outs(email);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_outs_domain ON opt_outs(domain);")

            # Gmail draft tracking table (for idempotency and recovery)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS draft_records (
                    lead_id TEXT PRIMARY KEY,
                    gmail_draft_id TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    subject TEXT,
                    created_at TEXT
                );
                """
            )

            conn.commit()
            logger.info("Database schema initialized successfully at %s", self.db_path)

    def is_opted_out(self, email: Optional[str] = None, domain: Optional[str] = None) -> bool:
        """Check if an email or domain is present on the opt-out suppression list."""
        norm_email = normalize_email(email)
        norm_domain = normalize_domain(domain)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if norm_email:
                cursor.execute("SELECT 1 FROM opt_outs WHERE email = ?", (norm_email,))
                if cursor.fetchone():
                    return True
            if norm_domain:
                cursor.execute("SELECT 1 FROM opt_outs WHERE domain = ?", (norm_domain,))
                if cursor.fetchone():
                    return True
        return False

    def add_opt_out(self, email: Optional[str] = None, domain: Optional[str] = None, reason: str = "User request") -> None:
        """Record an email or domain in the opt-out table and update existing leads."""
        norm_email = normalize_email(email)
        norm_domain = normalize_domain(domain)
        now_str = datetime.now().isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO opt_outs (email, domain, reason, opt_out_date)
                VALUES (?, ?, ?, ?)
                """,
                (norm_email or None, norm_domain or None, reason, now_str),
            )
            # Update leads table as well
            if norm_email:
                cursor.execute(
                    "UPDATE leads SET opt_out = 1, outreach_status = 'OPTED_OUT' WHERE email = ?",
                    (norm_email,),
                )
            if norm_domain:
                cursor.execute(
                    "UPDATE leads SET opt_out = 1, outreach_status = 'OPTED_OUT' WHERE domain = ?",
                    (norm_domain,),
                )
            conn.commit()
            logger.info("Added opt-out for email=%s, domain=%s", norm_email, norm_domain)

    def find_duplicate(self, lead: Lead) -> Optional[Lead]:
        """
        Check if a lead already exists by lead_id, or by normalized email, or by domain + person_name.
        """
        norm_email = normalize_email(lead.email)
        norm_domain = normalize_domain(lead.domain or lead.website)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. Exact lead_id
            if lead.lead_id:
                cursor.execute("SELECT * FROM leads WHERE lead_id = ?", (lead.lead_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_lead(row)

            # 2. Matching non-empty email
            if norm_email:
                cursor.execute("SELECT * FROM leads WHERE email = ?", (norm_email,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_lead(row)

            # 3. Matching domain and person name
            if norm_domain and lead.person_name:
                cursor.execute(
                    "SELECT * FROM leads WHERE domain = ? AND LOWER(person_name) = ?",
                    (norm_domain, lead.person_name.strip().lower()),
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_lead(row)

            # 4. Matching domain if no person name is present on both
            if norm_domain and not lead.person_name:
                cursor.execute(
                    "SELECT * FROM leads WHERE domain = ? AND (person_name IS NULL OR person_name = '')",
                    (norm_domain,),
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_lead(row)

        return None

    def upsert_lead(self, lead: Lead) -> Tuple[Lead, bool]:
        """
        Insert or update a lead record with deduplication.
        Preserves manual edits (notes, approval status) when merging updates.
        Returns: (Lead, is_new: bool)
        """
        existing = self.find_duplicate(lead)
        now_str = datetime.now().isoformat()

        # Check opt-out status
        if self.is_opted_out(lead.email, lead.domain):
            lead.opt_out = True
            lead.outreach_status = OutreachStatus.OPTED_OUT

        if existing:
            # Preserve manual edits and non-empty notes
            lead.lead_id = existing.lead_id  # maintain stable ID
            if existing.notes and not lead.notes:
                lead.notes = existing.notes
            if existing.approval_status != ApprovalStatus.PENDING and lead.approval_status == ApprovalStatus.PENDING:
                lead.approval_status = existing.approval_status
            if existing.gmail_draft_id and not lead.gmail_draft_id:
                lead.gmail_draft_id = existing.gmail_draft_id
                lead.outreach_status = OutreachStatus.DRAFT_CREATED
            if existing.last_contacted and not lead.last_contacted:
                lead.last_contacted = existing.last_contacted
            if existing.opt_out:
                lead.opt_out = True
                lead.outreach_status = OutreachStatus.OPTED_OUT

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE leads SET
                        company = ?, website = ?, domain = ?, description = ?, industry = ?,
                        location = ?, company_size = ?, company_source = ?, source_date = ?,
                        person_name = ?, designation = ?, professional_profile_url = ?,
                        email = ?, email_source = ?, verification_status = ?, relevance_score = ?,
                        relevance_reason = ?, personalization_fact = ?, personalization_source = ?,
                        subject = ?, email_body = ?, approval_status = ?, outreach_status = ?,
                        gmail_draft_id = ?, last_contacted = ?, follow_up_date = ?,
                        opt_out = ?, notes = ?, updated_at = ?
                    WHERE lead_id = ?
                    """,
                    (
                        lead.company, lead.website, lead.domain, lead.description, lead.industry,
                        lead.location, lead.company_size, lead.company_source, lead.source_date,
                        lead.person_name, lead.designation, lead.professional_profile_url,
                        lead.email, lead.email_source, lead.verification_status.value,
                        lead.relevance_score, lead.relevance_reason, lead.personalization_fact,
                        lead.personalization_source, lead.subject, lead.email_body,
                        lead.approval_status.value, lead.outreach_status.value,
                        lead.gmail_draft_id, lead.last_contacted, lead.follow_up_date,
                        1 if lead.opt_out else 0, lead.notes, now_str, lead.lead_id
                    ),
                )
                conn.commit()
            return lead, False
        else:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO leads (
                        lead_id, company, website, domain, description, industry,
                        location, company_size, company_source, source_date,
                        person_name, designation, professional_profile_url,
                        email, email_source, verification_status, relevance_score,
                        relevance_reason, personalization_fact, personalization_source,
                        subject, email_body, approval_status, outreach_status,
                        gmail_draft_id, last_contacted, follow_up_date,
                        opt_out, notes, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        lead.lead_id, lead.company, lead.website, lead.domain, lead.description, lead.industry,
                        lead.location, lead.company_size, lead.company_source, lead.source_date,
                        lead.person_name, lead.designation, lead.professional_profile_url,
                        lead.email, lead.email_source, lead.verification_status.value,
                        lead.relevance_score, lead.relevance_reason, lead.personalization_fact,
                        lead.personalization_source, lead.subject, lead.email_body,
                        lead.approval_status.value, lead.outreach_status.value,
                        lead.gmail_draft_id, lead.last_contacted, lead.follow_up_date,
                        1 if lead.opt_out else 0, lead.notes, now_str, now_str
                    ),
                )
                conn.commit()
            return lead, True

    def get_lead(self, lead_id: str) -> Optional[Lead]:
        """Fetch lead by lead_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_lead(row)
        return None

    def get_all_leads(self) -> List[Lead]:
        """Fetch all leads ordered by relevance score descending."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leads ORDER BY relevance_score DESC, company ASC")
            rows = cursor.fetchall()
            return [self._row_to_lead(r) for r in rows]

    def record_draft_creation(self, lead_id: str, gmail_draft_id: str, email: str, subject: str) -> None:
        """Record draft in draft_records table and update lead record."""
        now_str = datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO draft_records (lead_id, gmail_draft_id, recipient_email, subject, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (lead_id, gmail_draft_id, email, subject, now_str),
            )
            cursor.execute(
                """
                UPDATE leads
                SET gmail_draft_id = ?, outreach_status = 'DRAFT_CREATED', updated_at = ?
                WHERE lead_id = ?
                """,
                (gmail_draft_id, now_str, lead_id),
            )
            conn.commit()

    def has_draft_created(self, lead_id: str) -> bool:
        """Check if a Gmail draft has already been created for this lead."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM draft_records WHERE lead_id = ?", (lead_id,))
            if cursor.fetchone():
                return True
            cursor.execute(
                "SELECT 1 FROM leads WHERE lead_id = ? AND (gmail_draft_id != '' AND gmail_draft_id IS NOT NULL)",
                (lead_id,),
            )
            return cursor.fetchone() is not None

    def export_to_csv(self, filepath: Optional[str] = None) -> str:
        """Export all leads to a CSV file matching the exact 29 columns."""
        path = filepath or config.csv_data_path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        leads = self.get_all_leads()

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(SHEET_HEADERS)
            for lead in leads:
                writer.writerow(lead.to_sheet_row())

        logger.info("Exported %d leads to CSV at %s", len(leads), path)
        return path

    def import_from_csv(self, filepath: str) -> Tuple[int, int]:
        """
        Import leads from a CSV file.
        Returns: (new_count, updated_count)
        """
        if not Path(filepath).exists():
            logger.warning("CSV file does not exist: %s", filepath)
            return 0, 0

        new_count = 0
        updated_count = 0

        with open(filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if not headers:
                return 0, 0

            # If headers match SHEET_HEADERS, construct directly
            for row in reader:
                if not row or not any(row):
                    continue
                lead = Lead.from_sheet_row(row)
                _, is_new = self.upsert_lead(lead)
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

        logger.info("Imported %d new and %d updated leads from %s", new_count, updated_count, filepath)
        return new_count, updated_count

    def _row_to_lead(self, row: sqlite3.Row) -> Lead:
        d = dict(row)
        # Convert integer opt_out to bool
        d["opt_out"] = bool(d.get("opt_out", 0))
        # Ensure enums are valid
        return Lead(**d)


db = Database()
