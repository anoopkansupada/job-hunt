"""
Ashby API scraper -- fetches jobs from Ashby's public posting API.
No auth required.
"""
import hashlib
import requests


ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def fetch_ashby_jobs(company_slug: str) -> list[dict]:
    """Fetch all postings for a company from Ashby's public API."""
    url = ASHBY_API.format(slug=company_slug)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("jobs", [])
    except Exception:
        return []


def parse_ashby_job(posting: dict, company_name: str) -> dict:
    """Parse an Ashby posting into our standard job dict."""
    title = posting.get("title", "")
    url = posting.get("jobUrl") or posting.get("applyUrl", "")

    location = posting.get("location", "")
    if isinstance(location, dict):
        location = location.get("name", "")

    team = posting.get("department", "")
    if isinstance(team, dict):
        team = team.get("name", "")

    description = posting.get("descriptionPlain") or posting.get("description", "")

    posted_at = posting.get("publishedAt") or posting.get("updatedAt", "")

    employment_type = posting.get("employmentType", "")
    if location and employment_type:
        location = f"{location} ({employment_type})"

    # Hash for dedup
    raw = f"{company_name}_{title}_{url}"
    job_hash = hashlib.sha256(raw.encode()).hexdigest()

    return {
        "company_name": company_name,
        "title": title,
        "url": url,
        "source": "ashby",
        "location": location,
        "team": team,
        "description": description,
        "posted_at": posted_at,
        "hash": job_hash,
    }
