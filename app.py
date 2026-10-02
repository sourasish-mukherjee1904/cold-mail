"""
Streamlit Web Dashboard for Automated Winter Internship Outreach System.
Provides a visual interface for reviewing leads, inspecting transparent scores,
editing generated drafts, and executing safe Gmail draft generation.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from company_enrichment import company_enricher
from config import config
from database import db
from discovery import discovery_engine
from email_verification import email_verifier
from gmail_drafts import gmail_manager
from models import ApprovalStatus, Lead, OutreachStatus, VerificationStatus
from personalization import email_generator
from relevance import relevance_scorer
from sheets_store import sheets_store

st.set_page_config(
    page_title="Winter Internship Outreach 2026",
    page_icon="📬",
    layout="wide",
)

st.title("📬 Winter Internship Outreach System")
st.caption("AI-Powered Discovery, Truthful Personalization & Safe Gmail Draft Generation | Sourasish Mukherjee (IIT Kharagpur)")

# Sidebar: Profile & System Status
with st.sidebar:
    st.header("👤 Candidate Profile")
    st.write(f"**Name:** {config.profile.name}")
    st.write(f"**College:** {config.profile.college}")
    st.write(f"**Degree:** {config.profile.degree}")
    st.write(f"**GitHub:** [{config.profile.github_url}]({config.profile.github_url})")
    st.write(f"**Focus:** Intelligent Video Analytics, CV, AI/ML")

    st.markdown("---")
    st.header("⚙️ System Status")
    mode_text = "🟢 Google Sheets Connected" if not sheets_store.is_offline else "🟡 Offline CSV Mode (Local)"
    st.write(f"**Storage:** {mode_text}")
    st.write(f"**Hunter.io:** {'🟢 Configured' if config.is_hunter_configured() else '⚪ Not Configured (Free Fallback)'}")
    st.write(f"**Gmail API:** {'🟢 OAuth Ready' if gmail_manager.get_service() else '⚪ Credentials Needed for Live API'}")

    st.markdown("---")
    st.header("⚡ Quick Actions")
    if st.button("🔍 Discover Seed Startups", use_container_width=True):
        leads = discovery_engine.get_seed_startups(limit=10)
        for l in leads:
            db.upsert_lead(l)
        sheets_store.sync_all_leads()
        st.success(f"Discovered {len(leads)} startups!")
        st.rerun()

    if st.button("⚡ Score & Personalize All", use_container_width=True):
        all_leads = db.get_all_leads()
        for l in all_leads:
            company_enricher.enrich_lead(l)
            relevance_scorer.score_lead(l)
            email_generator.generate_email_content(l)
            db.upsert_lead(l)
        sheets_store.sync_all_leads()
        st.success(f"Processed {len(all_leads)} leads!")
        st.rerun()

# Fetch current leads
leads = db.get_all_leads()

# Top KPI metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Leads", len(leads))
col2.metric("Verified Emails", sum(1 for l in leads if l.verification_status == VerificationStatus.VERIFIED))
col3.metric("Approved Leads", sum(1 for l in leads if l.approval_status == ApprovalStatus.APPROVED))
col4.metric("Gmail Drafts Created", sum(1 for l in leads if l.gmail_draft_id))

st.markdown("---")

tab_review, tab_drafts, tab_explorer, tab_optout = st.tabs([
    "✍️ Lead Review & Approval",
    "✉️ Gmail Drafts Generator",
    "📊 Leads Explorer",
    "🛑 Opt-Out Management",
])

# ----------------- TAB 1: Lead Review & Approval -----------------
with tab_review:
    st.subheader("Interactive Lead Review & Email Approval")

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        app_filter = st.selectbox(
            "Filter by Approval Status",
            ["PENDING", "APPROVED", "REJECTED", "ALL"],
            index=0,
        )
    with filter_col2:
        ver_filter = st.selectbox(
            "Filter by Verification Status",
            ["ALL", "VERIFIED", "UNVERIFIED", "INVALID", "MISSING"],
            index=0,
        )

    # Filtered list
    review_leads = leads
    if app_filter != "ALL":
        review_leads = [l for l in review_leads if l.approval_status.value == app_filter]
    if ver_filter != "ALL":
        review_leads = [l for l in review_leads if l.verification_status.value == ver_filter]

    if not review_leads:
        st.info("No leads match the selected filters.")
    else:
        lead_options = {f"{l.company} ({l.person_name or 'Unknown'}) - Score: {l.relevance_score}/100": l for l in review_leads}
        selected_label = st.selectbox("Select Lead to Inspect & Review", list(lead_options.keys()))
        selected_lead = lead_options[selected_label]

        card_col1, card_col2 = st.columns([1, 1])

        with card_col1:
            st.markdown(f"### {selected_lead.company}")
            st.write(f"**Website:** [{selected_lead.website}]({selected_lead.website})")
            st.write(f"**Industry:** {selected_lead.industry}")
            st.write(f"**Location:** {selected_lead.location}")
            st.write(f"**Company Size:** {selected_lead.company_size}")
            st.write(f"**Description:** {selected_lead.description}")

            st.markdown("#### 🎯 Contact & Verification")
            st.write(f"**Name:** {selected_lead.person_name or 'Not identified'}")
            st.write(f"**Designation:** {selected_lead.designation or 'Not identified'}")
            st.write(f"**Email:** `{selected_lead.email or 'MISSING'}`")

            # Verification badge
            v_color = "green" if selected_lead.verification_status == VerificationStatus.VERIFIED else "orange"
            st.markdown(f"**Verification:** :{v_color}[{selected_lead.verification_status.value}]")
            st.caption(f"Source: {selected_lead.email_source or 'None'}")

            st.markdown("#### 📈 Relevance Score")
            st.progress(selected_lead.relevance_score / 100)
            st.write(f"**Score:** {selected_lead.relevance_score}/100")
            st.info(f"**Rationale:**\n{selected_lead.relevance_reason.replace(' | ', '\n* ')}")

        with card_col2:
            st.markdown("### 📝 Outreach Email Draft")
            new_subject = st.text_input("Subject Line", value=selected_lead.subject)
            new_body = st.text_area("Email Body", value=selected_lead.email_body, height=320)

            act_col1, act_col2, act_col3 = st.columns(3)
            with act_col1:
                if st.button("✅ Approve Lead", type="primary", use_container_width=True):
                    selected_lead.approval_status = ApprovalStatus.APPROVED
                    selected_lead.subject = new_subject
                    selected_lead.email_body = new_body
                    db.upsert_lead(selected_lead)
                    sheets_store.sync_lead(selected_lead)
                    st.success("Lead APPROVED!")
                    st.rerun()

            with act_col2:
                if st.button("❌ Reject Lead", use_container_width=True):
                    selected_lead.approval_status = ApprovalStatus.REJECTED
                    db.upsert_lead(selected_lead)
                    sheets_store.sync_lead(selected_lead)
                    st.warning("Lead REJECTED.")
                    st.rerun()

            with act_col3:
                if st.button("💾 Save Edits Only", use_container_width=True):
                    selected_lead.subject = new_subject
                    selected_lead.email_body = new_body
                    db.upsert_lead(selected_lead)
                    sheets_store.sync_lead(selected_lead)
                    st.success("Email edits saved.")
                    st.rerun()

            st.markdown("---")
            with st.expander("✏️ Update Email Address Manually"):
                manual_email = st.text_input("Verified Email Address", value=selected_lead.email)
                manual_source = st.text_input("Source URL (e.g. Website contact page)", value=selected_lead.website)
                mark_verified = st.checkbox("Mark as VERIFIED deliverable", value=True)
                if st.button("Update Contact Email"):
                    email_verifier.record_manual_email(
                        selected_lead, manual_email, manual_source, is_verified=mark_verified
                    )
                    relevance_scorer.score_lead(selected_lead)
                    email_generator.generate_email_content(selected_lead)
                    db.upsert_lead(selected_lead)
                    sheets_store.sync_lead(selected_lead)
                    st.success("Email updated and lead rescored.")
                    st.rerun()

# ----------------- TAB 2: Gmail Drafts Generator -----------------
with tab_drafts:
    st.subheader("Safe Gmail Draft Generation")
    st.markdown(
        """
        > [!IMPORTANT]
        > **Strict Safety Approval Gates:** A Gmail draft will **only** be created if:
        > 1. The lead is explicitly **APPROVED**.
        > 2. The email address is **VERIFIED**.
        > 3. The contact is **NOT opted out**.
        > 4. No prior draft or email has ever been created (**Idempotent protection**).
        """
    )

    ready_leads = [
        l for l in leads
        if l.approval_status == ApprovalStatus.APPROVED
        and l.verification_status == VerificationStatus.VERIFIED
        and not l.gmail_draft_id
        and not l.opt_out
    ]

    st.write(f"**Leads Ready for Draft Creation:** {len(ready_leads)}")

    dry_run_mode = st.checkbox("Dry-Run Simulation Mode (Safe: validates without calling Gmail API)", value=True)

    if st.button("🚀 Process Drafts Now", type="primary"):
        if not ready_leads:
            st.warning("No approved leads with verified emails are ready for draft creation.")
        else:
            with st.spinner("Processing drafts through safety gates..."):
                summary = gmail_manager.process_approved_batch(ready_leads, dry_run=dry_run_mode)
                st.success(
                    f"Done! Created: {summary['created']} | Skipped: {summary['skipped']} | Failed: {summary['failed']}"
                )
                for det in summary["details"]:
                    status_icon = "✅" if det["status"] == "CREATED" else "⚠️"
                    st.write(f"{status_icon} **{det['lead_id']}**: {det['message']}")
            st.rerun()

# ----------------- TAB 3: Leads Explorer -----------------
with tab_explorer:
    st.subheader("All Leads Explorer")
    if leads:
        df_rows = [l.to_sheet_row() for l in leads]
        df = pd.DataFrame(df_rows, columns=SHEET_HEADERS)
        # Display selected readable columns
        cols_to_show = [
            "company", "industry", "location", "person_name", "designation",
            "email", "verification_status", "relevance_score", "approval_status",
            "outreach_status", "gmail_draft_id"
        ]
        # Align with available dataframe columns
        valid_cols = [c for c in cols_to_show if c in df.columns]
        st.dataframe(df[valid_cols] if valid_cols else df, use_container_width=True)

        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Full Leads CSV (29 Columns)",
            data=csv_data,
            file_name="winter_internship_leads_2026.csv",
            mime="text/csv",
        )
    else:
        st.info("No leads in database yet. Click 'Discover Seed Startups' in sidebar to start.")

# ----------------- TAB 4: Opt-Out Management -----------------
with tab_optout:
    st.subheader("🛑 Suppression & Opt-Out List")
    st.write("Contacts or domains added here will be permanently excluded from future drafts.")

    opt_email = st.text_input("Email to Suppress")
    opt_domain = st.text_input("Domain to Suppress (e.g. example.com)")
    opt_reason = st.text_input("Reason", value="User request / Unsubscribe")

    if st.button("Add to Suppression List"):
        if opt_email or opt_domain:
            db.add_opt_out(email=opt_email, domain=opt_domain, reason=opt_reason)
            sheets_store.sync_all_leads()
            st.success(f"Added opt-out for {opt_email or opt_domain}")
            st.rerun()
        else:
            st.warning("Please provide an email or domain.")
