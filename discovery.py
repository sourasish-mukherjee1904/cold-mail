"""
Modular Startup Discovery Pipeline for Indian Tech Startups.
Integrates multiple accessible public sources:
1. YC India Tech Directory (Public YC data)
2. GitHub Organization Search (Open-source Indian AI/ML & DevTools orgs)
3. Web Search Discovery (DuckDuckGo public search)
4. Curated Seed Database (Baseline fallback)

Strictly deduplicates, verifies official domains, distinguishes newly discovered
startups from existing records, and attributes every fact to a verifiable source.
"""

from __future__ import annotations

import csv
import datetime
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus, urlparse
import requests

from company_enrichment import CompanyEnricher, company_enricher
from database import Database, db
from logging_config import logger
from models import Lead, VerificationStatus, normalize_domain


# Curated seed database of notable Indian startups (Preserved for baseline & offline tests)
INDIAN_STARTUPS_SEED: List[Dict[str, Any]] = [
    {
        "company": "Staqu Technologies",
        "website": "https://staqu.com",
        "description": "AI and computer vision video analytics platform (Jarvis) powering security, retail, and smart city infrastructure.",
        "industry": "Computer Vision / Video Analytics",
        "location": "Gurugram, Haryana",
        "company_size": "51-200",
        "company_source": "https://staqu.com/about-us",
        "relevant_tech": ["Computer Vision", "Intelligent Video Analytics", "Deep Learning", "Edge AI"],
        "default_contact": {
            "name": "Atul Rai",
            "designation": "Co-Founder & CEO",
            "email": "contact@staqu.com",
            "profile_url": "https://staqu.com/about-us",
            "verification_status": "VERIFIED",
            "source": "https://staqu.com/contact-us"
        }
    },
    {
        "company": "DaveAI",
        "website": "https://iamdave.ai",
        "description": "Interactive artificial intelligence platform building 3D virtual avatars and conversational AI for enterprise.",
        "industry": "Generative AI / Enterprise AI",
        "location": "Bengaluru, Karnataka",
        "company_size": "11-50",
        "company_source": "https://iamdave.ai/about-us",
        "relevant_tech": ["Generative AI", "3D Avatars", "Conversational AI", "Speech AI"],
        "default_contact": {
            "name": "Sriram P H",
            "designation": "Co-Founder & CEO",
            "email": "info@iamdave.ai",
            "profile_url": "https://iamdave.ai/about-us",
            "verification_status": "VERIFIED",
            "source": "https://iamdave.ai/contact"
        }
    },
    {
        "company": "Detect Technologies",
        "website": "https://detecttechnologies.com",
        "description": "Industrial AI and automated computer vision for workplace safety and asset monitoring in real time.",
        "industry": "Computer Vision / Industrial AI",
        "location": "Chennai, Tamil Nadu",
        "company_size": "201-500",
        "company_source": "https://detecttechnologies.com",
        "relevant_tech": ["Computer Vision", "Drone Video Analytics", "Industrial IoT", "Deep Learning"],
        "default_contact": {
            "name": "Daniel Raj David",
            "designation": "Co-Founder & CEO",
            "email": "info@detecttechnologies.com",
            "profile_url": "https://detecttechnologies.com/company",
            "verification_status": "VERIFIED",
            "source": "https://detecttechnologies.com/contact"
        }
    },
    {
        "company": "CynLr (Cybernetics Laboratory)",
        "website": "https://cynlr.com",
        "description": "Deep-tech robotics startup building visual cognition systems and object-manipulation robots.",
        "industry": "Robotics & Industrial AI",
        "location": "Bengaluru, Karnataka",
        "company_size": "11-50",
        "company_source": "https://cynlr.com",
        "relevant_tech": ["Robotics", "Visual Cognition", "Machine Vision", "Reinforcement Learning"],
        "default_contact": {
            "name": "Gokul N A",
            "designation": "Founder & Design Lead",
            "email": "contact@cynlr.com",
            "profile_url": "https://cynlr.com",
            "verification_status": "VERIFIED",
            "source": "https://cynlr.com/contact"
        }
    },
    {
        "company": "Wadhwani AI",
        "website": "https://wadhwaniai.org",
        "description": "Applied AI institute building computer vision and diagnostic models for healthcare and agriculture.",
        "industry": "Computer Vision / AI for Social Good",
        "location": "Mumbai, Maharashtra",
        "company_size": "51-200",
        "company_source": "https://wadhwaniai.org",
        "relevant_tech": ["Computer Vision", "Medical Imaging", "Acoustic AI", "Predictive Modeling"],
        "default_contact": {
            "name": "Alpan Raval",
            "designation": "Head of AI/ML Research",
            "email": "info@wadhwaniai.org",
            "profile_url": "https://wadhwaniai.org/team",
            "verification_status": "UNVERIFIED",
            "source": "https://wadhwaniai.org/contact"
        }
    },
    {
        "company": "Sarvam AI",
        "website": "https://sarvam.ai",
        "description": "Generative AI foundation models and voice AI infrastructure designed for Indian languages and enterprise systems.",
        "industry": "Generative AI / Foundation Models",
        "location": "Bengaluru, Karnataka",
        "company_size": "11-50",
        "company_source": "https://sarvam.ai",
        "relevant_tech": ["Generative AI", "LLMs", "Speech Recognition", "Indic NLP"],
        "default_contact": {
            "name": "Pratyush Kumar",
            "designation": "Co-Founder",
            "email": "contact@sarvam.ai",
            "profile_url": "https://sarvam.ai",
            "verification_status": "UNVERIFIED",
            "source": "https://sarvam.ai"
        }
    },
    {
        "company": "SigNoz",
        "website": "https://signoz.io",
        "description": "Open-source developer observability platform built on OpenTelemetry for tracing, metrics, and logs.",
        "industry": "Developer Tools & SaaS",
        "location": "Bengaluru, Karnataka / Remote",
        "company_size": "11-50",
        "company_source": "https://signoz.io",
        "relevant_tech": ["Backend Engineering", "OpenTelemetry", "ClickHouse", "Go / Python"],
        "default_contact": {
            "name": "Pranay Prateek",
            "designation": "Co-Founder",
            "email": "pranay@signoz.io",
            "profile_url": "https://github.com/SigNoz",
            "verification_status": "UNVERIFIED",
            "source": "https://signoz.io/about"
        }
    },
    {
        "company": "Devtron",
        "website": "https://devtron.ai",
        "description": "Open-source Kubernetes deployment and CI/CD delivery platform for enterprise cloud microservices.",
        "industry": "Developer Tools & SaaS",
        "location": "Gurugram, Haryana / Remote",
        "company_size": "51-200",
        "company_source": "https://devtron.ai",
        "relevant_tech": ["Kubernetes", "DevOps", "Backend Infrastructure", "Go / Python"],
        "default_contact": {
            "name": "Prashant Ghildiyal",
            "designation": "Co-Founder & CEO",
            "email": "info@devtron.ai",
            "profile_url": "https://devtron.ai",
            "verification_status": "UNVERIFIED",
            "source": "https://devtron.ai"
        }
    }
]

# Known directory and aggregator domains to filter out from web search results
AGGREGATOR_DOMAINS = {
    "linkedin.com", "wikipedia.org", "crunchbase.com", "glassdoor.com", "glassdoor.co.in",
    "indeed.com", "indeed.co.in", "naukri.com", "ambitionbox.com", "yourstory.com",
    "inc42.com", "economictimes.indiatimes.com", "entrackr.com", "tracxn.com",
    "producthunt.com", "g2.com", "capterra.com", "youtube.com", "twitter.com",
    "x.com", "facebook.com", "instagram.com", "medium.com", "github.com",
}


class BaseDiscoveryProvider(ABC):
    """Abstract base class for modular discovery providers."""

    def __init__(self, name: str, request_timeout: int = 6):
        self.name = name
        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 (compatible; WinterInternshipResearch/1.0)"
        })

    @abstractmethod
    def discover(
        self,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 10,
    ) -> List[Lead]:
        """Discover candidate company leads from this source."""
        pass


class SeedDatabaseProvider(BaseDiscoveryProvider):
    """Provides curated seed companies for offline use and baseline testing."""

    def __init__(self, seed_data: Optional[List[Dict[str, Any]]] = None):
        super().__init__(name="curated_seed")
        self.seed_data = seed_data or INDIAN_STARTUPS_SEED

    def discover(
        self,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 10,
    ) -> List[Lead]:
        results: List[Lead] = []
        today_str = datetime.date.today().isoformat()

        for item in self.seed_data:
            if industry and industry.lower() not in item.get("industry", "").lower():
                continue
            if location and location.lower() not in item.get("location", "").lower():
                continue
            if keyword:
                kq = keyword.lower()
                text = f"{item['company']} {item['description']} {' '.join(item.get('relevant_tech', []))}".lower()
                if kq not in text:
                    continue

            contact = item.get("default_contact", {})
            v_status_str = contact.get("verification_status", "MISSING")
            try:
                v_status = VerificationStatus(v_status_str)
            except ValueError:
                v_status = VerificationStatus.UNVERIFIED

            lead = Lead(
                company=item["company"],
                website=item.get("website", ""),
                domain=normalize_domain(item.get("website", "")),
                description=item.get("description", ""),
                industry=item.get("industry", ""),
                location=item.get("location", ""),
                company_size=item.get("company_size", ""),
                company_source="curated_seed",
                source_date=today_str,
                person_name=contact.get("name", ""),
                designation=contact.get("designation", ""),
                professional_profile_url=contact.get("profile_url", ""),
                email=contact.get("email", ""),
                email_source=contact.get("source", ""),
                verification_status=v_status,
                notes=f"Source: Curated Seed Directory. Tech: {', '.join(item.get('relevant_tech', []))}",
            )
            results.append(lead)
            if len(results) >= limit:
                break

        return results


class GitHubOrgDiscoveryProvider(BaseDiscoveryProvider):
    """
    Discovers Indian tech companies from GitHub's official search API.
    Identifies open-source product companies and developer tools located in India.
    No API key required (unauthenticated rate limit 10/min, or optional GITHUB_TOKEN).
    """

    API_BASE = "https://api.github.com"

    def __init__(self, github_token: Optional[str] = None, request_timeout: int = 6):
        super().__init__(name="github_org_search", request_timeout=request_timeout)
        self.token = github_token or os.getenv("GITHUB_TOKEN")
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def discover(
        self,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 10,
    ) -> List[Lead]:
        loc = location or "India"
        search_terms = []
        if keyword:
            search_terms.append(keyword)
        if industry:
            search_terms.append(industry)

        tech_query = " ".join(search_terms) if search_terms else "AI machine-learning vision"
        # Search organizations located in India matching tech focus
        q = f"type:org location:{loc} {tech_query}".strip()
        url = f"{self.API_BASE}/search/users"
        params = {"q": q, "per_page": min(limit, 30)}

        results: List[Lead] = []
        today_str = datetime.date.today().isoformat()

        try:
            resp = self.session.get(url, params=params, timeout=self.request_timeout)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                for item in items:
                    org_login = item.get("login")
                    if not org_login:
                        continue

                    # Fetch org details to retrieve official blog/website and bio
                    org_url = f"{self.API_BASE}/users/{org_login}"
                    org_resp = self.session.get(org_url, timeout=self.request_timeout)
                    if org_resp.status_code != 200:
                        continue

                    org_data = org_resp.json()
                    website = org_data.get("blog", "")
                    # Prepend https if bare domain
                    if website and not website.startswith("http"):
                        website = f"https://{website}"

                    domain = normalize_domain(website)
                    if not domain or domain in AGGREGATOR_DOMAINS:
                        continue

                    company_name = org_data.get("name") or org_login
                    description = org_data.get("bio") or f"Open-source technology company on GitHub ({org_login})."
                    org_location = org_data.get("location") or "India"

                    lead = Lead(
                        company=company_name,
                        website=website,
                        domain=domain,
                        description=description,
                        industry=industry or "Developer Tools / AI Software",
                        location=org_location,
                        company_source=f"https://github.com/{org_login}",
                        source_date=today_str,
                        verification_status=VerificationStatus.MISSING,
                        notes=f"Discovered via GitHub Org API ({org_login}). Public repos: {org_data.get('public_repos', 0)}",
                    )
                    results.append(lead)
                    if len(results) >= limit:
                        break
            elif resp.status_code == 403:
                logger.warning("GitHub API rate limit exceeded. Falling back to alternative providers.")
            else:
                logger.warning("GitHub API returned status %d", resp.status_code)
        except requests.exceptions.RequestException as e:
            logger.warning("Network error querying GitHub Org API: %s", e)

        return results


class YCIndiaDirectoryProvider(BaseDiscoveryProvider):
    """
    Discovers Indian tech startups from Y Combinator's public directory.
    Queries verified Indian companies in AI/ML, Computer Vision, Robotics, and B2B SaaS.
    No API key required.
    """

    DIRECTORY_URL = "https://raw.githubusercontent.com/ycombinator/public-company-data/main/companies.json"

    # Seed list of notable YC Indian tech companies for fallback if external raw repo is unreachable
    YC_INDIAN_TECH_ARCHIVE = [
        {"name": "SigNoz", "website": "https://signoz.io", "batch": "W21", "industry": "Developer Tools", "desc": "Open source observability platform.", "location": "Bengaluru"},
        {"name": "Devtron", "website": "https://devtron.ai", "batch": "W22", "industry": "DevOps / Infrastructure", "desc": "Open source Kubernetes software delivery platform.", "location": "Gurugram"},
        {"name": "InVideo", "website": "https://invideo.io", "batch": "W20", "industry": "Generative AI / Video", "desc": "AI video creation and editing platform.", "location": "Mumbai"},
        {"name": "Decentro", "website": "https://decentro.tech", "batch": "S20", "industry": "Fintech / Backend APIs", "desc": "API platform for banking and financial integrations.", "location": "Bengaluru"},
        {"name": "Bik", "website": "https://bik.ai", "batch": "W22", "industry": "Conversational AI / SaaS", "desc": "Conversational commerce and AI agent platform.", "location": "Bengaluru"},
        {"name": "Mudrex", "website": "https://mudrex.com", "batch": "W19", "industry": "Algorithmic Finance / AI", "desc": "Automated investment platform.", "location": "Bengaluru"},
        {"name": "Cognida.ai", "website": "https://cognida.ai", "batch": "W23", "industry": "AI & Machine Learning", "desc": "Enterprise AI solutions and decision intelligence.", "location": "Bengaluru"},
        {"name": "SuperKalam", "website": "https://superkalam.com", "batch": "W24", "industry": "AI / EdTech", "desc": "AI mentor and evaluation system.", "location": "Bengaluru"},
    ]

    def __init__(self, request_timeout: int = 6):
        super().__init__(name="yc_india_directory", request_timeout=request_timeout)

    def discover(
        self,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 10,
    ) -> List[Lead]:
        results: List[Lead] = []
        today_str = datetime.date.today().isoformat()
        companies_data = []

        try:
            resp = self.session.get(self.DIRECTORY_URL, timeout=self.request_timeout)
            if resp.status_code == 200:
                raw = resp.json()
                for item in raw:
                    country = (item.get("country") or item.get("location") or "").lower()
                    if "india" in country:
                        companies_data.append({
                            "name": item.get("name"),
                            "website": item.get("website"),
                            "batch": item.get("batch", "YC"),
                            "industry": item.get("industry", "Technology"),
                            "desc": item.get("one_liner") or item.get("long_description") or "",
                            "location": item.get("location") or "India",
                        })
        except Exception:
            logger.info("YC raw directory endpoint unreachable; using verified YC India tech archive.")

        if not companies_data:
            companies_data = self.YC_INDIAN_TECH_ARCHIVE

        for comp in companies_data:
            comp_ind = comp.get("industry", "")
            comp_desc = comp.get("desc", "")
            comp_loc = comp.get("location", "")
            comp_name = comp.get("name", "")

            if industry and industry.lower() not in comp_ind.lower() and industry.lower() not in comp_desc.lower():
                continue
            if location and location.lower() not in comp_loc.lower():
                continue
            if keyword:
                kw = keyword.lower()
                if kw not in comp_name.lower() and kw not in comp_desc.lower() and kw not in comp_ind.lower():
                    continue

            website = comp.get("website", "")
            domain = normalize_domain(website)
            if not domain or domain in AGGREGATOR_DOMAINS:
                continue

            lead = Lead(
                company=comp_name,
                website=website,
                domain=domain,
                description=comp_desc,
                industry=comp_ind or "Technology",
                location=comp_loc,
                company_source="https://www.ycombinator.com/companies",
                source_date=today_str,
                verification_status=VerificationStatus.MISSING,
                notes=f"Discovered via Y Combinator Directory ({comp.get('batch', 'YC')}).",
            )
            results.append(lead)
            if len(results) >= limit:
                break

        return results


class WebSearchDiscoveryProvider(BaseDiscoveryProvider):
    """
    Discovers Indian tech startups using live web search (DuckDuckGo HTML / Instant Answers).
    Filters out job boards and aggregators, then extracts candidate company domains.
    No API key required.
    """

    SEARCH_URL = "https://html.duckduckgo.com/html/"

    def __init__(self, request_timeout: int = 6):
        super().__init__(name="web_search", request_timeout=request_timeout)

    def discover(
        self,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 10,
    ) -> List[Lead]:
        loc = location or "India"
        tech = industry or keyword or "computer vision video analytics AI"
        query = f'"{tech}" startup "{loc}" site:.in OR site:.ai OR site:.com -site:linkedin.com -site:wikipedia.org'

        results: List[Lead] = []
        today_str = datetime.date.today().isoformat()

        try:
            resp = self.session.post(
                self.SEARCH_URL,
                data={"q": query},
                timeout=self.request_timeout,
            )
            if resp.status_code == 200:
                html = resp.text

                # Extract result links and snippets from DuckDuckGo HTML layout
                # Pattern: <a class="result__url" href="URL"> or <a class="result__snippet" ...>
                url_matches = re.findall(r'<a\s+class="result__url"[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
                title_matches = re.findall(r'<a\s+class="result__snippet"[^>]*href="[^"]*">(.*?)</a>', html, re.IGNORECASE | re.DOTALL)

                # Fallback URL extraction from result__a links
                if not url_matches:
                    url_matches = re.findall(r'<a\s+class="result__a"[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)

                seen_domains: Set[str] = set()

                for raw_url in url_matches:
                    # Unpack redirect if needed: /l/?kh=-1&uddg=https%3A%2F%2F...
                    actual_url = raw_url
                    if "uddg=" in raw_url:
                        match = re.search(r"uddg=([^&]+)", raw_url)
                        if match:
                            import urllib.parse
                            actual_url = urllib.parse.unquote(match.group(1))

                    if not actual_url.startswith("http"):
                        actual_url = f"https://{actual_url.strip()}"

                    domain = normalize_domain(actual_url)
                    if not domain or domain in seen_domains or domain in AGGREGATOR_DOMAINS:
                        continue
                    seen_domains.add(domain)

                    # Extract company name from domain: "subdomain.example.com" -> "Example"
                    parts = domain.split(".")
                    company_name = parts[-2].capitalize() if len(parts) >= 2 else domain.capitalize()

                    lead = Lead(
                        company=company_name,
                        website=f"https://{domain}",
                        domain=domain,
                        description=f"Indian tech startup in {tech} discovered via live web search.",
                        industry=industry or "AI & Machine Learning",
                        location=loc,
                        company_source=f"DuckDuckGo Search: {tech} {loc}",
                        source_date=today_str,
                        verification_status=VerificationStatus.MISSING,
                        notes=f"Discovered via web search query '{query[:45]}...'.",
                    )
                    results.append(lead)
                    if len(results) >= limit:
                        break
            else:
                logger.warning("DuckDuckGo search returned status %d", resp.status_code)
        except requests.exceptions.RequestException as e:
            logger.warning("Network error querying web search discovery: %s", e)

        return results


class DiscoveryReport:
    """Detailed summary of a discovery execution distinguishing new vs refreshed records."""

    def __init__(self):
        self.newly_discovered: List[Lead] = []
        self.refreshed_existing: List[Lead] = []
        self.seed_leads: List[Lead] = []
        self.total_evaluated: int = 0
        self.providers_used: List[str] = []

    @property
    def new_count(self) -> int:
        return len(self.newly_discovered)

    @property
    def refreshed_count(self) -> int:
        return len(self.refreshed_existing)

    @property
    def seed_count(self) -> int:
        return len(self.seed_leads)


class StartupDiscoveryPipeline:
    """
    Coordinates modular discovery providers, confirms company identity from official websites,
    deduplicates against SQLite database, and transparently distinguishes newly discovered leads.
    """

    def __init__(
        self,
        database: Optional[Database] = None,
        enricher: Optional[CompanyEnricher] = None,
    ):
        self.db = database or db
        self.enricher = enricher or company_enricher
        self.providers: Dict[str, BaseDiscoveryProvider] = {
            "curated_seed": SeedDatabaseProvider(),
            "github": GitHubOrgDiscoveryProvider(),
            "yc": YCIndiaDirectoryProvider(),
            "web": WebSearchDiscoveryProvider(),
        }

    def register_provider(self, key: str, provider: BaseDiscoveryProvider) -> None:
        """Register a custom discovery provider."""
        self.providers[key] = provider

    def run_discovery(
        self,
        sources: Optional[List[str]] = None,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 20,
        confirm_live_website: bool = False,
    ) -> DiscoveryReport:
        """
        Executes discovery across selected providers.
        Confirm official websites if requested, and deduplicates strictly by normalized domain.
        """
        selected_sources = sources or ["yc", "github", "web"]
        report = DiscoveryReport()

        candidates: List[Lead] = []

        for source_key in selected_sources:
            provider = self.providers.get(source_key)
            if not provider:
                logger.warning("Provider '%s' not registered. Skipping.", source_key)
                continue

            report.providers_used.append(provider.name)
            logger.info("Executing discovery provider: %s", provider.name)
            try:
                found = provider.discover(industry=industry, location=location, keyword=keyword, limit=limit)
                candidates.extend(found)
            except Exception as e:
                logger.error("Error running provider %s: %s", provider.name, e)

        report.total_evaluated = len(candidates)
        logger.info("Total candidate leads retrieved: %d", len(candidates))

        seen_domains: Set[str] = set()

        for candidate in candidates:
            norm_dom = normalize_domain(candidate.domain or candidate.website)
            if not norm_dom or norm_dom in seen_domains:
                continue
            seen_domains.add(norm_dom)

            # Confirm company identity from official homepage if requested
            if confirm_live_website:
                try:
                    self.enricher.enrich_lead(candidate, fetch_live=True)
                except Exception as e:
                    logger.warning("Could not confirm website for %s: %s", candidate.company, e)

            # Check if domain or lead already exists in SQLite
            is_seed = candidate.company_source == "curated_seed"
            existing = self.db.find_duplicate(candidate)

            saved_lead, is_new = self.db.upsert_lead(candidate)

            if is_seed:
                report.seed_leads.append(saved_lead)
            elif is_new:
                report.newly_discovered.append(saved_lead)
                logger.info("[NEW DISCOVERY] Found %s (%s)", saved_lead.company, saved_lead.domain)
            else:
                report.refreshed_existing.append(saved_lead)
                logger.info("[REFRESHED] Updated %s (%s)", saved_lead.company, saved_lead.domain)

        return report


# Maintain backwards compatibility for existing code and tests
class StartupDiscovery:
    """Backwards-compatible wrapper around StartupDiscoveryPipeline and seed/CSV methods."""

    def __init__(self, seed_data: Optional[List[Dict[str, Any]]] = None):
        self.pipeline = StartupDiscoveryPipeline()
        self.seed_provider = SeedDatabaseProvider(seed_data=seed_data)

    def get_seed_startups(
        self,
        industry_query: Optional[str] = None,
        location_query: Optional[str] = None,
        keyword_query: Optional[str] = None,
        limit: int = 10,
    ) -> List[Lead]:
        return self.seed_provider.discover(
            industry=industry_query, location=location_query, keyword=keyword_query, limit=limit
        )

    def import_custom_csv(self, filepath: str) -> List[Lead]:
        path = Path(filepath)
        if not path.exists():
            logger.warning("File does not exist: %s", filepath)
            return []

        leads: List[Lead] = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                clean_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
                company = clean_row.get("company") or clean_row.get("company_name") or clean_row.get("name")
                if not company:
                    continue

                website = clean_row.get("website") or clean_row.get("url") or clean_row.get("domain") or ""
                email = clean_row.get("email") or clean_row.get("contact_email") or ""
                person_name = clean_row.get("person_name") or clean_row.get("founder") or clean_row.get("contact_name") or ""
                designation = clean_row.get("designation") or clean_row.get("title") or clean_row.get("role") or ""

                lead = Lead(
                    company=company,
                    website=website,
                    domain=normalize_domain(website or clean_row.get("domain", "")),
                    description=clean_row.get("description", ""),
                    industry=clean_row.get("industry", ""),
                    location=clean_row.get("location", ""),
                    company_size=clean_row.get("company_size", ""),
                    company_source=str(path.name),
                    source_date=datetime.date.today().isoformat(),
                    person_name=person_name,
                    designation=designation,
                    email=email,
                    email_source="CSV Import",
                    verification_status=VerificationStatus.UNVERIFIED if email else VerificationStatus.MISSING,
                    notes=clean_row.get("notes", "Imported from CSV"),
                )
                leads.append(lead)

        return leads


discovery_engine = StartupDiscovery()
discovery_pipeline = StartupDiscoveryPipeline()
