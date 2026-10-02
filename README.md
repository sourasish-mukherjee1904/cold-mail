# Automated Winter Internship Outreach System

An automated, local-first Python system built for **Sourasish Mukherjee** (IIT Kharagpur, Manufacturing Science & Engineering) to discover Indian product startups, identify engineering decision-makers, score lead relevance, generate truthful personalized cold emails, and safely create Gmail drafts for manual review.

---

## 🌟 Key Architecture & Safety Features

1. **Zero-Cost & Local-First by Default:** Runs 100% locally out-of-the-box using SQLite and offline CSV storage (`data/leads.csv`). No paid subscriptions or cloud credentials required to run, test, score, or preview leads.
2. **Canonical 29-Column Google Sheets Schema:** Exactly preserves column sequence, incremental synchronization, and custom manual notes without overwriting.
3. **Multi-Point Safety Approval Gates:** A Gmail draft is created **only** when:
   - Lead is explicitly marked `APPROVED`.
   - Email is confirmed `VERIFIED`.
   - Contact is **not** on the opt-out suppression list.
   - Lead has **not** already been contacted (`outreach_status != SENT`).
   - No prior draft ID exists in SQLite or Google Sheets (Idempotent guard).
4. **Zero Automated Sending:** Uses the narrow `gmail.compose` scope to create **drafts only**. You inspect and send every email manually in Gmail.
5. **Zero Hallucination Personalization:** Uses strictly verified company facts connected to your confirmed **Intelligent Video Analytics Platform**, deep learning models, and IIT Kharagpur coursework. Never hallucinates metrics, non-existent job openings, or candidate credentials.
6. **Hunter.io Integration with Free Fallback:** Supports domain search, email finder, and verification while defensively handling HTTP 401, 403, and 429 quota exhaustion. Provides full manual email entry with source attribution.

---

## 📁 Project Structure

```
cold-mail/
├── config.py                 # Pydantic & dotenv configuration, validated student profile
├── models.py                 # Core domain models, Enums, exact 29-column row serialization
├── database.py               # SQLite storage, multi-key deduplication, opt-out suppression, draft recovery
├── discovery.py              # Curated Indian startups seed database, filters, custom CSV importer
├── company_enrichment.py     # Safe website inspection, domain normalization, technical area tagging
├── contact_discovery.py      # Decision-maker discovery & role prioritization matrix (CTO, AI Lead, etc.)
├── email_verification.py     # Hunter.io API client, RFC 5322 syntax, disposable email filter, manual fallback
├── relevance.py              # Transparent 0-100 rubric with explainable reason breakdown
├── personalization.py        # Truthful deterministic email template generator (<150 words)
├── sheets_store.py           # Google Sheets integration (gspread) with backoff retry & offline CSV fallback
├── gmail_drafts.py           # Narrow OAuth draft manager with strict approval gates & crash recovery
├── cli.py                    # Complete command-line interface (scriptable subcommands & interactive menu)
├── app.py                    # Streamlit visual dashboard (review, approve, preview, drafts, opt-outs)
├── logging_config.py         # Secure logging with credential and token redaction
├── requirements.txt          # Python dependencies
├── pytest.ini                # Pytest configuration
├── .env.example              # Environment variables template
├── .gitignore                # Excludes secrets, databases, tokens, virtual environments
├── data/
│   ├── sample_leads.csv      # Seed test leads in exact 29-column schema
│   └── leads.csv             # Local offline leads store
└── tests/                    # Automated test suite (32 tests passing)
    ├── test_deduplication.py
    ├── test_discovery_enrichment.py
    ├── test_email_validation.py
    ├── test_personalization.py
    ├── test_sheets_sync.py
    ├── test_approval_gates.py
    └── test_draft_recovery.py
```

---

## 🚀 Quick Start Guide (Offline Mode - Zero Credentials Needed)

### 1. Activate Virtual Environment
```bash
cd "/Users/sourasishmukherjee/Desktop/cold mail"
source .venv/bin/activate
```

### 2. Run All Automated Unit Tests
```bash
pytest tests/ -v
```
*(All 32 tests run offline using mocks without external API calls or sending emails.)*

### 3. Run Complete Pipeline via CLI
```bash
# Ingest seed Indian startups, enrich, score relevance, and generate personalized emails:
python cli.py run-all
```

### 4. Interactive Review & Approval Terminal
```bash
python cli.py review
```
*Allows inspecting company facts, reading the relevance rationale, previewing the email, editing text, and pressing `[A]` to Approve or `[R]` to Reject.*

### 5. Launch the Streamlit Web Dashboard
```bash
streamlit run app.py
```
*Open http://localhost:8501 in your browser to inspect leads, edit email bodies, approve/reject leads, and generate drafts with a visual interface.*

---

## 🛠️ Configuration & Credentials Guide

### Step 1: Copy Environment Template
```bash
cp .env.example .env
```

Edit `.env` to configure your profile URLs:
```env
PROFILE_NAME=Sourasish Mukherjee
COLLEGE=IIT Kharagpur
DEGREE=Manufacturing Science and Engineering
RESUME_URL=https://your-portfolio-or-resume.pdf
GITHUB_URL=https://github.com/sourasish
PORTFOLIO_URL=
INTERNSHIP_START_DATE=2026-12-01
INTERNSHIP_END_DATE=2026-01-15
PREFERRED_LOCATIONS=India, Remote, Bengaluru, Hyderabad, Gurugram, Pune
PREFERRED_ROLES=AI/ML Intern, Computer Vision Intern, Backend Engineering Intern
```

---

### Step 2: Google Sheets Setup (Optional for Live Cloud Sync)

> [!NOTE]
> If Google Sheets is not configured, the system automatically uses `data/leads.csv`.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable both **Google Sheets API** and **Google Drive API**.
3. Go to **APIs & Services > Credentials > Create Credentials > Service Account**.
4. Download the Service Account JSON key, rename it to `service_account.json`, and place it in the project root.
5. Create a Google Spreadsheet named `Winter Internship Outreach 2026`.
6. Click **Share** on your spreadsheet and share it with the service account client email (with **Editor** permissions).
7. Copy the spreadsheet ID from the URL and add to `.env`:
   ```env
   SPREADSHEET_ID=your_spreadsheet_id_here
   ```

---

### Step 3: Gmail API OAuth Setup (For Live Drafts)

1. In the same Google Cloud Console project, enable the **Gmail API**.
2. Go to **APIs & Services > OAuth consent screen**:
   - Choose **External** (or Internal if using Google Workspace).
   - Set App name (e.g. `Internship Outreach Drafts`).
   - Add your Gmail address as a **Test User**.
3. Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**:
   - Application type: **Desktop app**.
   - Download the client JSON, rename it to `credentials.json`, and place it in the project root.
4. When you trigger live draft creation (`python cli.py create-drafts` without `--dry-run`), a local browser window will open requesting consent for the `gmail.compose` scope.
5. Once approved, `token.json` is generated locally and automatically refreshed for future runs.

---

### Step 4: Hunter.io API Setup (Optional for Email Finding)

1. Sign up for a free account at [Hunter.io](https://hunter.io/).
2. Copy your API key and add it to `.env`:
   ```env
   HUNTER_API_KEY=your_hunter_api_key_here
   ```
*Free tier limits (25 searches/month) are handled defensively. If exhausted (HTTP 429), the system falls back to syntax validation and manual entry.*

---

## 💻 CLI Command Reference

| Command | Description |
| :--- | :--- |
| `python cli.py` | Launches the interactive terminal menu |
| `python cli.py run-all` | Runs discovery \(\to\) enrichment \(\to\) scoring \(\to\) personalization |
| `python cli.py discover --industry "Computer Vision"` | Imports startups filtered by domain |
| `python cli.py import-csv <path>` | Imports custom CSV file (custom or 29-column schema) |
| `python cli.py enrich` | Enriches company metadata and classifies technical focus |
| `python cli.py score` | Evaluates 0–100 transparent relevance rubric |
| `python cli.py personalize` | Generates truthful personalized email drafts |
| `python cli.py list` | Displays tabular overview of all leads, scores, and statuses |
| `python cli.py review` | Interactive review: inspect facts, preview email, approve/reject |
| `python cli.py create-drafts --dry-run` | Simulates draft generation against all safety gates |
| `python cli.py create-drafts` | Creates live Gmail drafts for all approved leads |
| `python cli.py opt-out --email <email>` | Adds address to opt-out suppression list |
| `python cli.py export-csv` | Exports database to canonical 29-column CSV |

---

## 🔒 Safety & Privacy Principles

- **Never Guesses Deliverability:** Unverified naming heuristics (`first.last@domain.com`) are kept as `UNVERIFIED` and cannot pass draft generation gates.
- **Opt-Out Compliance:** Any email or domain added to the opt-out list is immediately flagged and blocked from draft creation.
- **Restart Recovery:** Created draft IDs are saved in SQLite `draft_records` before subsequent network steps. Re-running the application will never produce duplicate drafts in your Gmail.
- **Credential Protection:** `.gitignore` excludes `.env`, `credentials.json`, `service_account.json`, `token.json`, and database files. Sensitive tokens in log files are automatically redacted.

---

## 🧪 Testing

Run all unit tests at any time:
```bash
./.venv/bin/pytest tests/ -v
```
All 32 tests execute in under 0.5s with zero external network dependencies.
