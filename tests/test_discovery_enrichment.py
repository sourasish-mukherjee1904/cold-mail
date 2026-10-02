"""
Unit tests for startup discovery, filtering, CSV import, and company enrichment.
Uses mocks to ensure offline stability without relying on external websites.
"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
import requests

from company_enrichment import CompanyEnricher
from discovery import StartupDiscovery
from models import Lead, VerificationStatus


def test_seed_startup_discovery_filtering():
    discovery = StartupDiscovery()

    # Filter by industry: Computer Vision
    cv_startups = discovery.get_seed_startups(industry_query="Computer Vision")
    assert len(cv_startups) >= 2
    for s in cv_startups:
        assert "vision" in s.industry.lower() or "video" in s.industry.lower()
        assert s.domain != ""
        assert s.lead_id.startswith("lead_")

    # Filter by location: Gurugram
    gurugram_startups = discovery.get_seed_startups(location_query="Gurugram")
    assert len(gurugram_startups) >= 1
    for s in gurugram_startups:
        assert "gurugram" in s.location.lower()

    # Filter by keyword: "robotics"
    robotics = discovery.get_seed_startups(keyword_query="robotics")
    assert len(robotics) >= 1
    assert any("cynlr" in r.company.lower() for r in robotics)


def test_custom_csv_import():
    discovery = StartupDiscovery()
    csv_content = """company,website,industry,location,person_name,designation,email
AgriTech Vision,https://agritechvision.in,Computer Vision,Pune,Rajesh Kumar,CTO,rajesh@agritechvision.in
RoboWorks,https://roboworks.ai,Robotics,Bengaluru,Pooja Sharma,Founder,pooja@roboworks.ai
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        f.flush()
        temp_csv_path = f.name

    try:
        leads = discovery.import_custom_csv(temp_csv_path)
        assert len(leads) == 2
        assert leads[0].company == "AgriTech Vision"
        assert leads[0].domain == "agritechvision.in"
        assert leads[0].person_name == "Rajesh Kumar"
        assert leads[0].email == "rajesh@agritechvision.in"
        assert leads[0].verification_status == VerificationStatus.UNVERIFIED
        assert leads[1].company == "RoboWorks"
    finally:
        if os.path.exists(temp_csv_path):
            os.remove(temp_csv_path)


def test_company_enrichment_mocked_http():
    enricher = CompanyEnricher()

    mock_html = """
    <html>
      <head>
        <title>OmniVision AI - Intelligent Video Analytics and Edge AI</title>
        <meta name="description" content="Deploy real-time computer vision models on edge devices with OmniVision.">
      </head>
      <body>
        <h1>Welcome</h1>
        <a href="/careers">Join our careers & internship program</a>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html

    with patch.object(enricher.session, "get", return_value=mock_resp):
        lead = Lead(
            company="OmniVision AI",
            website="https://omnivision.ai",
        )
        enriched = enricher.enrich_lead(lead, fetch_live=True)

        assert enriched.domain == "omnivision.ai"
        assert "real-time computer vision" in enriched.description
        assert enriched.company_source == "https://omnivision.ai"
        assert "careers or hiring section detected" in enriched.notes.lower()
        assert enriched.industry == "Computer Vision & Video Analytics"


def test_company_enrichment_resilience_to_errors():
    enricher = CompanyEnricher()

    # Test HTTP timeout resilience
    with patch.object(enricher.session, "get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        lead = Lead(company="Timeout Tech", website="https://timeouttech.in")
        enriched = enricher.enrich_lead(lead, fetch_live=True)
        # Should not crash and should preserve original fields
        assert enriched.company == "Timeout Tech"
        assert enriched.domain == "timeouttech.in"

    # Test HTTP 500 error resilience
    mock_500 = MagicMock()
    mock_500.status_code = 500
    with patch.object(enricher.session, "get", return_value=mock_500):
        lead2 = Lead(company="Server Error Corp", website="https://servererror.in")
        enriched2 = enricher.enrich_lead(lead2, fetch_live=True)
        assert enriched2.company == "Server Error Corp"
