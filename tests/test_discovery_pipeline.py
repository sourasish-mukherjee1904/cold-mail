"""
Unit tests for the live modular startup discovery pipeline and providers.
Uses mocks to ensure 100% offline stability without external network dependencies.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from database import Database
from discovery import (
    GitHubOrgDiscoveryProvider,
    StartupDiscoveryPipeline,
    WebSearchDiscoveryProvider,
    YCIndiaDirectoryProvider,
)
from models import Lead, VerificationStatus


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    tdb = Database(db_path=path)
    yield tdb
    if os.path.exists(path):
        os.remove(path)


def test_github_org_discovery_mocked():
    provider = GitHubOrgDiscoveryProvider()

    # Mock /search/users
    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 200
    mock_search_resp.json.return_value = {
        "items": [
            {"login": "visiontech-india"},
            {"login": "robotics-labs-in"},
        ]
    }

    # Mock /users/{org}
    mock_org_resp_1 = MagicMock()
    mock_org_resp_1.status_code = 200
    mock_org_resp_1.json.return_value = {
        "login": "visiontech-india",
        "name": "VisionTech India",
        "blog": "https://visiontech.in",
        "bio": "Intelligent video stream analytics and edge vision.",
        "location": "Bengaluru, India",
        "public_repos": 14,
    }

    mock_org_resp_2 = MagicMock()
    mock_org_resp_2.status_code = 200
    mock_org_resp_2.json.return_value = {
        "login": "robotics-labs-in",
        "name": "Robotics Labs India",
        "blog": "https://roboticslabs.ai",
        "bio": "Autonomous manipulation and visual perception.",
        "location": "Hyderabad, India",
        "public_repos": 8,
    }

    def mock_get(url, *args, **kwargs):
        if "search/users" in url:
            return mock_search_resp
        elif "visiontech-india" in url:
            return mock_org_resp_1
        elif "robotics-labs-in" in url:
            return mock_org_resp_2
        return MagicMock(status_code=404)

    with patch.object(provider.session, "get", side_effect=mock_get):
        leads = provider.discover(industry="Computer Vision", limit=5)
        assert len(leads) == 2
        assert leads[0].company == "VisionTech India"
        assert leads[0].domain == "visiontech.in"
        assert leads[0].company_source == "https://github.com/visiontech-india"
        assert "visiontech-india" in leads[0].notes


def test_yc_india_directory_discovery_mocked():
    provider = YCIndiaDirectoryProvider()

    mock_yc_data = [
        {
            "name": "Sarvam AI",
            "website": "https://sarvam.ai",
            "country": "India",
            "industry": "Artificial Intelligence",
            "one_liner": "Foundation models for Indian languages.",
            "location": "Bengaluru, India",
            "batch": "S23",
        },
        {
            "name": "SiliconValley Tech",
            "website": "https://svtech.com",
            "country": "United States",  # Non-India, should be filtered out
            "industry": "AI",
            "one_liner": "US startup.",
        },
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_yc_data

    with patch.object(provider.session, "get", return_value=mock_resp):
        leads = provider.discover(industry="Artificial Intelligence", limit=5)
        assert len(leads) == 1
        assert leads[0].company == "Sarvam AI"
        assert leads[0].domain == "sarvam.ai"
        assert leads[0].company_source == "https://www.ycombinator.com/companies"
        assert "S23" in leads[0].notes


def test_web_search_discovery_mocked():
    provider = WebSearchDiscoveryProvider()

    # Mock DuckDuckGo HTML layout containing company URL and Wikipedia/LinkedIn (which must be filtered out)
    mock_html = """
    <html>
      <body>
        <a class="result__url" href="https://cynlr.com">cynlr.com</a>
        <a class="result__url" href="https://in.linkedin.com/company/some-company">linkedin.com</a>
        <a class="result__url" href="https://en.wikipedia.org/wiki/Computer_vision">wikipedia.org</a>
        <a class="result__url" href="https://detecttechnologies.com">detecttechnologies.com</a>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html

    with patch.object(provider.session, "post", return_value=mock_resp):
        leads = provider.discover(industry="Computer Vision", location="India", limit=5)
        # LinkedIn and Wikipedia must be filtered out
        domains = [l.domain for l in leads]
        assert "cynlr.com" in domains
        assert "detecttechnologies.com" in domains
        assert "linkedin.com" not in domains
        assert "wikipedia.org" not in domains


def test_pipeline_deduplication_and_reporting(temp_db):
    pipeline = StartupDiscoveryPipeline(database=temp_db)

    # Mock a provider returning 2 candidates
    mock_provider = MagicMock()
    mock_provider.name = "mock_provider"
    mock_provider.discover.return_value = [
        Lead(company="Alpha Vision", website="https://alphavision.ai", domain="alphavision.ai"),
        Lead(company="Beta Robotics", website="https://betarobotics.in", domain="betarobotics.in"),
    ]

    pipeline.register_provider("mock", mock_provider)

    # Run 1: Genuinely new discoveries
    report_1 = pipeline.run_discovery(sources=["mock"], limit=5)
    assert report_1.total_evaluated == 2
    assert report_1.new_count == 2
    assert report_1.refreshed_count == 0
    assert report_1.newly_discovered[0].company == "Alpha Vision"

    # Run 2: Re-running with identical leads -> Must NOT create duplicates, must count as refreshed
    report_2 = pipeline.run_discovery(sources=["mock"], limit=5)
    assert report_2.total_evaluated == 2
    assert report_2.new_count == 0
    assert report_2.refreshed_count == 2

    # Check database lead count: exactly 2 leads, zero duplicates
    all_leads = temp_db.get_all_leads()
    assert len(all_leads) == 2


def test_curated_seed_not_reported_as_newly_discovered(temp_db):
    pipeline = StartupDiscoveryPipeline(database=temp_db)

    # Run discovery on seed provider only
    report = pipeline.run_discovery(sources=["curated_seed"], limit=3)
    # Seed leads must be recognized as seed_leads, NOT newly_discovered
    assert report.new_count == 0
    assert report.seed_count == 3
    for seed_lead in report.seed_leads:
        assert seed_lead.company_source == "curated_seed"
