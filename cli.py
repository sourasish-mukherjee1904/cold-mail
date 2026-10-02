"""
Command-Line Interface for the Automated Winter Internship Outreach System.
Supports interactive menus and scriptable CLI subcommands.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from company_enrichment import company_enricher
from config import config
from contact_discovery import contact_discovery
from database import db
from discovery import discovery_engine, discovery_pipeline
from email_verification import email_verifier, HunterClient
from gmail_drafts import gmail_manager
from logging_config import logger
from models import ApprovalStatus, Lead, OutreachStatus, VerificationStatus
from personalization import email_generator
from relevance import relevance_scorer
from sheets_store import sheets_store


def cmd_discover(
    industry: Optional[str] = None,
    location: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
    source: str = "all",
    confirm_live: bool = False,
) -> None:
    """Discover startups from public sources and save to database with transparent reporting."""
    source_map = {
        "all": ["yc", "github", "web", "curated_seed"],
        "web": ["web"],
        "github": ["github"],
        "yc": ["yc"],
        "seed": ["curated_seed"],
        "curated_seed": ["curated_seed"],
    }
    selected_sources = source_map.get(source.lower(), ["yc", "github", "web", "curated_seed"])

    print(f"\n[*] Executing Live Startup Discovery Pipeline...")
    print(f"    Sources:      {', '.join(selected_sources)}")
    print(f"    Industry:     {industry or 'All'}")
    print(f"    Location:     {location or 'All'}")
    print(f"    Keyword:      {keyword or 'None'}")
    print(f"    Limit:        {limit}")
    print(f"    Confirm Live: {confirm_live}")
    print("-" * 65)

    report = discovery_pipeline.run_discovery(
        sources=selected_sources,
        industry=industry,
        location=location,
        keyword=keyword,
        limit=limit,
        confirm_live_website=confirm_live,
    )

    sheets_store.sync_all_leads()

    print("\n" + "=" * 65)
    print("DISCOVERY PIPELINE EXECUTION REPORT:")
    print(f"Total Evaluated Candidates:    {report.total_evaluated}")
    print(f"Genuinely Newly Discovered:     {report.new_count}")
    print(f"Existing Records Refreshed:     {report.refreshed_count}")
    print(f"Curated Seed Leads (Baseline):  {report.seed_count}")
    print(f"Providers Utilized:            {', '.join(report.providers_used)}")
    print("=" * 65)

    if report.newly_discovered:
        print("\n✨ NEWLY DISCOVERED STARTUPS:")
        for idx, lead in enumerate(report.newly_discovered, 1):
            print(f"  {idx}. {lead.company:<24} | {lead.domain:<22} | Source: {lead.company_source}")
    elif report.refreshed_count > 0:
        print("\n[i] All discovered candidates were already in your database (refreshed successfully).")
    else:
        print("\n[i] No new startups found matching the specific criteria.")


def cmd_import_csv(filepath: str) -> None:
    """Import companies from custom CSV."""
    print(f"\n[*] Importing leads from CSV: {filepath}...")
    leads = discovery_engine.import_custom_csv(filepath)
    if not leads:
        # Try importing as 29-column schema
        new_cnt, upd_cnt = db.import_from_csv(filepath)
        print(f"[+] Ingested 29-column CSV: {new_cnt} new, {upd_cnt} updated.")
    else:
        new_cnt = 0
        upd_cnt = 0
        for l in leads:
            _, is_new = db.upsert_lead(l)
            if is_new:
                new_cnt += 1
            else:
                upd_cnt += 1
        print(f"[+] Ingested custom CSV: {new_cnt} new, {upd_cnt} updated.")
    sheets_store.sync_all_leads()


def cmd_enrich(fetch_live: bool = False) -> None:
    """Enrich all stored companies with normalized domains and technical tags."""
    print(f"\n[*] Enriching company profiles (Fetch live website: {fetch_live})...")
    leads = db.get_all_leads()
    for lead in leads:
        company_enricher.enrich_lead(lead, fetch_live=fetch_live)
        db.upsert_lead(lead)
    sheets_store.sync_all_leads()
    print(f"[+] Enriched {len(leads)} leads successfully.")


def cmd_score() -> None:
    """Calculate transparent 0-100 relevance scores for all leads."""
    print("\n[*] Scoring leads with transparent relevance rubric...")
    leads = db.get_all_leads()
    for lead in leads:
        score, reason = relevance_scorer.score_lead(lead)
        db.upsert_lead(lead)
    sheets_store.sync_all_leads()
    print(f"[+] Scored {len(leads)} leads.")


def cmd_personalize() -> None:
    """Generate truthful email subject and bodies based on confirmed facts."""
    print("\n[*] Generating personalized outreach emails...")
    leads = db.get_all_leads()
    for lead in leads:
        email_generator.generate_email_content(lead)
        db.upsert_lead(lead)
    sheets_store.sync_all_leads()
    print(f"[+] Personalized email drafts generated for {len(leads)} leads.")


def cmd_list(min_score: int = 0) -> None:
    """List all leads with their score, status, and verification."""
    leads = db.get_all_leads()
    filtered = [l for l in leads if l.relevance_score >= min_score]
    print(f"\n{'ID':<15} | {'Company':<22} | {'Contact':<18} | {'Email Status':<12} | {'Score':<5} | {'Approval':<10} | {'Draft ID'}")
    print("-" * 110)
    for l in filtered:
        draft = (l.gmail_draft_id[:12] + "...") if l.gmail_draft_id else "-"
        contact = (l.person_name[:16] + "..") if len(l.person_name) > 16 else (l.person_name or "Unknown")
        print(
            f"{l.lead_id:<15} | {l.company[:20]:<22} | {contact:<18} | "
            f"{l.verification_status.value:<12} | {l.relevance_score:<5} | {l.approval_status.value:<10} | {draft}"
        )
    print("-" * 110)
    print(f"Total: {len(filtered)} leads displayed.")


def cmd_review() -> None:
    """Interactive review terminal for inspecting, previewing, and approving leads."""
    leads = db.get_all_leads()
    pending = [l for l in leads if l.approval_status == ApprovalStatus.PENDING]

    if not pending:
        print("\n[+] No pending leads to review! All leads have been processed.")
        return

    print(f"\n[*] Starting interactive review for {len(pending)} pending leads...")
    for idx, lead in enumerate(pending, 1):
        print("\n" + "=" * 80)
        print(f"[{idx}/{len(pending)}] Lead ID: {lead.lead_id} | Company: {lead.company} ({lead.website})")
        print(f"Industry: {lead.industry} | Location: {lead.location} | Size: {lead.company_size}")
        print(f"Contact: {lead.person_name} ({lead.designation or 'No formal designation'})")
        print(f"Email: {lead.email or 'MISSING'} | Verification: {lead.verification_status.value} (Source: {lead.email_source})")
        print(f"Relevance Score: {lead.relevance_score}/100")
        print(f"Rationale: {lead.relevance_reason}")
        print("-" * 80)
        print("PREVIEW SUBJECT:", lead.subject or "[No subject generated yet]")
        print("PREVIEW BODY:\n", lead.email_body or "[No body generated yet]")
        print("=" * 80)

        choice = input("[A]pprove / [R]eject / [E]dit email / [M]anual email / [S]kip / [Q]uit: ").strip().lower()
        if choice == "a":
            lead.approval_status = ApprovalStatus.APPROVED
            db.upsert_lead(lead)
            sheets_store.sync_lead(lead)
            print("[+] Lead APPROVED.")
        elif choice == "r":
            lead.approval_status = ApprovalStatus.REJECTED
            db.upsert_lead(lead)
            sheets_store.sync_lead(lead)
            print("[-] Lead REJECTED.")
        elif choice == "m":
            new_email = input("Enter verified professional email: ").strip()
            new_source = input("Enter source URL (e.g. company contact page): ").strip()
            email_verifier.record_manual_email(lead, new_email, new_source, is_verified=True)
            relevance_scorer.score_lead(lead)
            email_generator.generate_email_content(lead)
            db.upsert_lead(lead)
            sheets_store.sync_lead(lead)
            print(f"[+] Updated email to {new_email} (VERIFIED).")
        elif choice == "e":
            print("Enter new email body (type EOF or single dot '.' on a new line to finish):")
            lines = []
            while True:
                line = input()
                if line.strip() == "." or line.strip() == "EOF":
                    break
                lines.append(line)
            lead.email_body = "\n".join(lines)
            db.upsert_lead(lead)
            sheets_store.sync_lead(lead)
            print("[+] Email body updated.")
        elif choice == "q":
            break


def cmd_create_drafts(dry_run: bool = False) -> None:
    """Create Gmail drafts for leads that pass all safety gates."""
    leads = db.get_all_leads()
    approved = [l for l in leads if l.approval_status == ApprovalStatus.APPROVED]

    if not approved:
        print("\n[-] No leads currently marked APPROVED. Run 'python cli.py review' to approve leads first.")
        return

    mode_str = "DRY RUN (No real drafts)" if dry_run else "LIVE GMAIL DRAFTS"
    print(f"\n[*] Processing {len(approved)} approved leads [{mode_str}]...")

    summary = gmail_manager.process_approved_batch(approved, dry_run=dry_run)
    print("\n" + "=" * 60)
    print("DRAFT CREATION SUMMARY:")
    print(f"Total Reviewed:  {summary['total_submitted']}")
    print(f"Drafts Created:  {summary['created']}")
    print(f"Skipped/Blocked: {summary['skipped']}")
    print(f"Failed:          {summary['failed']}")
    print("=" * 60)
    for det in summary["details"]:
        print(f"- {det['lead_id']}: [{det['status']}] {det['message']}")


def cmd_opt_out(email: Optional[str] = None, domain: Optional[str] = None, reason: str = "User request") -> None:
    """Record opt-out suppression."""
    if not email and not domain:
        print("[-] Please specify --email or --domain to opt-out.")
        return
    db.add_opt_out(email=email, domain=domain, reason=reason)
    sheets_store.sync_all_leads()
    print(f"[+] Opt-out recorded for email={email}, domain={domain}.")


def cmd_export_csv(filepath: Optional[str] = None) -> None:
    """Export all leads to CSV."""
    path = filepath or config.csv_data_path
    db.export_to_csv(path)
    print(f"[+] Leads successfully exported to {path}")


def interactive_menu() -> None:
    """Full terminal interactive menu."""
    while True:
        print("\n" + "=" * 55)
        print("  AUTOMATED WINTER INTERNSHIP OUTREACH SYSTEM")
        print("  Sourasish Mukherjee | IIT Kharagpur (Offline Mode)")
        print("=" * 55)
        print("1. Discover Startups (Seed Directory)")
        print("2. Import Custom CSV")
        print("3. Enrich Company Information & Tag Tech")
        print("4. Score Relevance (Transparent 0-100 Rubric)")
        print("5. Generate Personalized Emails (Zero Hallucination)")
        print("6. List & Inspect Leads")
        print("7. Review & Approve Leads (Interactive)")
        print("8. Create Gmail Drafts (Dry-Run)")
        print("9. Create Live Gmail Drafts")
        print("10. Add Email/Domain to Opt-Out List")
        print("11. Export Leads to CSV")
        print("12. Sync All Leads to Google Sheets / Local Store")
        print("0. Exit")
        print("-" * 55)

        choice = input("Enter choice (0-12): ").strip()
        if choice == "1":
            ind = input("Filter by industry (e.g. 'Computer Vision', Enter to skip): ").strip() or None
            loc = input("Filter by location (e.g. 'Bengaluru', Enter to skip): ").strip() or None
            kw = input("Filter by keyword (e.g. 'video analytics', Enter to skip): ").strip() or None
            src = input("Source [all/web/github/yc/seed] (default 'all'): ").strip() or "all"
            conf = input("Confirm official websites live? (y/N): ").strip().lower() == "y"
            cmd_discover(industry=ind, location=loc, keyword=kw, source=src, confirm_live=conf)
        elif choice == "2":
            path = input("Enter path to CSV file: ").strip()
            cmd_import_csv(path)
        elif choice == "3":
            live = input("Fetch live websites? (y/N): ").strip().lower() == "y"
            cmd_enrich(fetch_live=live)
        elif choice == "4":
            cmd_score()
        elif choice == "5":
            cmd_personalize()
        elif choice == "6":
            min_s = input("Filter minimum score (0-100, default 0): ").strip()
            cmd_list(min_score=int(min_s) if min_s.isdigit() else 0)
        elif choice == "7":
            cmd_review()
        elif choice == "8":
            cmd_create_drafts(dry_run=True)
        elif choice == "9":
            confirm = input("Are you sure you want to create real Gmail drafts? (y/N): ").strip().lower()
            if confirm == "y":
                cmd_create_drafts(dry_run=False)
        elif choice == "10":
            em = input("Email to suppress (Enter to skip): ").strip() or None
            dm = input("Domain to suppress (Enter to skip): ").strip() or None
            cmd_opt_out(email=em, domain=dm)
        elif choice == "11":
            p = input("Export path (default data/leads.csv): ").strip() or None
            cmd_export_csv(p)
        elif choice == "12":
            res = sheets_store.sync_all_leads()
            print(f"[+] Synchronized {res['total']} leads ({res['created']} created, {res['updated']} updated).")
        elif choice == "0":
            print("Exiting. Best of luck with winter internship outreach!")
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Winter Internship Outreach System CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Discover
    p_disc = subparsers.add_parser("discover", help="Discover startups from public web sources, GitHub, YC, and seed directories")
    p_disc.add_argument("--industry", help="Industry keyword filter (e.g. 'Computer Vision', 'AI/ML')")
    p_disc.add_argument("--location", help="Location filter (e.g. 'India', 'Bengaluru')")
    p_disc.add_argument("--keyword", help="Technical keyword filter")
    p_disc.add_argument("--limit", type=int, default=20, help="Max startups to query per source")
    p_disc.add_argument("--source", choices=["all", "web", "github", "yc", "seed"], default="all", help="Discovery provider")
    p_disc.add_argument("--confirm-live", action="store_true", help="Fetch official homepage to confirm metadata")

    # Import
    p_imp = subparsers.add_parser("import-csv", help="Import leads from CSV")
    p_imp.add_argument("path", help="Path to CSV file")

    # Pipeline steps
    subparsers.add_parser("enrich", help="Enrich company metadata")
    subparsers.add_parser("score", help="Score relevance 0-100")
    subparsers.add_parser("personalize", help="Generate personalized email drafts")
    subparsers.add_parser("list", help="List leads in database")
    subparsers.add_parser("review", help="Interactive terminal review and approval")

    # Drafts
    p_draft = subparsers.add_parser("create-drafts", help="Create Gmail drafts for approved leads")
    p_draft.add_argument("--dry-run", action="store_true", help="Simulate without calling Gmail API")

    # Export
    p_exp = subparsers.add_parser("export-csv", help="Export leads to CSV")
    p_exp.add_argument("--path", help="Destination CSV path")

    # Opt out
    p_opt = subparsers.add_parser("opt-out", help="Add contact or domain to suppression list")
    p_opt.add_argument("--email", help="Email to block")
    p_opt.add_argument("--domain", help="Domain to block")

    # Run complete pipeline
    subparsers.add_parser("run-all", help="Execute complete discovery -> enrich -> score -> personalize pipeline")

    args = parser.parse_args()

    if not args.command:
        interactive_menu()
    elif args.command == "discover":
        cmd_discover(
            industry=args.industry,
            location=args.location,
            keyword=args.keyword,
            limit=args.limit,
            source=args.source,
            confirm_live=args.confirm_live,
        )
    elif args.command == "import-csv":
        cmd_import_csv(args.path)
    elif args.command == "enrich":
        cmd_enrich()
    elif args.command == "score":
        cmd_score()
    elif args.command == "personalize":
        cmd_personalize()
    elif args.command == "list":
        cmd_list()
    elif args.command == "review":
        cmd_review()
    elif args.command == "create-drafts":
        cmd_create_drafts(dry_run=args.dry_run)
    elif args.command == "export-csv":
        cmd_export_csv(args.path)
    elif args.command == "opt-out":
        cmd_opt_out(email=args.email, domain=args.domain)
    elif args.command == "run-all":
        cmd_discover()
        cmd_enrich()
        cmd_score()
        cmd_personalize()
        cmd_list()


if __name__ == "__main__":
    main()
