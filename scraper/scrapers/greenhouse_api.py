"""
Greenhouse API scraper -- fetches jobs from Greenhouse's public board API.
No auth required.
"""
import hashlib
import re
import requests


GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def fetch_greenhouse_jobs(company_slug: str) -> list[dict]:
    """Fetch all postings for a company from Greenhouse's public API."""
    url = GREENHOUSE_API.format(slug=company_slug)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("jobs", [])
    except Exception:
        return []


def _strip_html(html: str) -> str:
    """Basic HTML tag stripping."""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<li>", "- ", text)
    text = re.sub(r"</?(ul|ol|p|div|h[1-6]|span|strong|em|b|i|a)[^>]*>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#\d+;", "", text)
    return text.strip()


def parse_greenhouse_job(posting: dict, company_name: str) -> dict:
    """Parse a Greenhouse posting into our standard job dict."""
    title = posting.get("title", "")
    url = posting.get("absolute_url", "")

    # Location
    location_obj = posting.get("location", {})
    location = location_obj.get("name", "") if isinstance(location_obj, dict) else ""

    # Department / team
    departments = posting.get("departments", [])
    team = departments[0].get("name", "") if departments else ""

    # Description
    content = posting.get("content", "")
    description = _strip_html(content) if content else ""

    posted_at = posting.get("updated_at") or posting.get("first_published_at", "")

    # Hash for dedup
    raw = f"{company_name}_{title}_{url}"
    job_hash = hashlib.sha256(raw.encode()).hexdigest()

    return {
        "company_name": company_name,
        "title": title,
        "url": url,
        "source": "greenhouse",
        "location": location,
        "team": team,
        "description": description,
        "posted_at": posted_at,
        "hash": job_hash,
    }
