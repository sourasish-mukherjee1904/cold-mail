"""
Central configuration module for Winter Internship Outreach.
Loads environment variables safely, validates profile info, and provides fallbacks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


class StudentProfile(BaseSettings):
    """Sourasish Mukherjee's validated profile details."""
    name: str = Field(default="Sourasish Mukherjee", alias="PROFILE_NAME")
    college: str = Field(default="IIT Kharagpur", alias="COLLEGE")
    degree: str = Field(default="Manufacturing Science and Engineering", alias="DEGREE")
    resume_url: str = Field(default="", alias="RESUME_URL")
    github_url: str = Field(default="https://github.com/sourasish", alias="GITHUB_URL")
    portfolio_url: str = Field(default="", alias="PORTFOLIO_URL")
    internship_start_date: str = Field(default="2026-12-01", alias="INTERNSHIP_START_DATE")
    internship_end_date: str = Field(default="2026-01-15", alias="INTERNSHIP_END_DATE")
    preferred_locations: str = Field(
        default="India, Remote, Bengaluru, Hyderabad, Gurugram, Noida, Pune, Mumbai",
        alias="PREFERRED_LOCATIONS",
    )
    preferred_roles: str = Field(
        default="AI/ML Intern, Computer Vision Intern, Backend Engineering Intern, Data Science Intern",
        alias="PREFERRED_ROLES",
    )

    # Strictly confirmed technical skills & projects (Zero hallucination)
    technical_skills: List[str] = [
        "Artificial Intelligence & Machine Learning",
        "Computer Vision & Video Analytics",
        "Python, C++, SQL, Data Analysis",
        "Backend & Full-Stack Development",
        "Practical AI Application & Prototype Building",
    ]
    confirmed_projects: List[str] = [
        "Intelligent Video Analytics Platform: Computer vision and deep learning pipelines for real-time video stream processing and event detection.",
        "Full-stack software applications and practical AI prototypes.",
    ]


class AppConfig(BaseSettings):
    """System-wide configuration, APIs, and file paths."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google Sheets / Cloud
    spreadsheet_id: Optional[str] = Field(default=None, alias="SPREADSHEET_ID")
    spreadsheet_title: str = "Winter Internship Outreach 2026"
    worksheet_name: str = "Leads"
    service_account_file: str = Field(default="service_account.json", alias="GOOGLE_SERVICE_ACCOUNT_FILE")
    client_secret_file: str = Field(default="credentials.json", alias="GOOGLE_CLIENT_SECRET_FILE")
    gmail_token_file: str = Field(default="token.json", alias="GMAIL_TOKEN_FILE")

    # Hunter.io API
    hunter_api_key: Optional[str] = Field(default=None, alias="HUNTER_API_KEY")

    # Local storage paths
    sqlite_db_path: str = Field(default="outreach.db", alias="SQLITE_DB_PATH")
    csv_data_path: str = Field(default=str(BASE_DIR / "data" / "leads.csv"), alias="CSV_DATA_PATH")
    sample_csv_path: str = Field(default=str(BASE_DIR / "data" / "sample_leads.csv"), alias="SAMPLE_CSV_PATH")
    opt_out_csv_path: str = Field(default=str(BASE_DIR / "data" / "opt_out.csv"), alias="OPT_OUT_CSV_PATH")

    # Outreach tuning
    max_body_words: int = Field(default=150, alias="MAX_BODY_WORDS")
    email_tone: str = Field(default="professional_concise", alias="EMAIL_TONE")
    dry_run: bool = Field(default=False, alias="DRY_RUN")

    # Profile
    profile: StudentProfile = Field(default_factory=StudentProfile)

    def is_sheets_configured(self) -> bool:
        """Check if Google Sheets credentials and ID are available."""
        if not self.spreadsheet_id:
            return False
        sa_exists = Path(self.service_account_file).exists()
        oauth_exists = Path(self.client_secret_file).exists()
        return sa_exists or oauth_exists

    def is_hunter_configured(self) -> bool:
        """Check if Hunter API key is provided and non-empty."""
        return bool(self.hunter_api_key and len(self.hunter_api_key.strip()) > 5)


config = AppConfig()
