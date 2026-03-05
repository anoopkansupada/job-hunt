"""
Lever API scraper -- fetches jobs from Lever's public posting API.
No auth required.
"""
import hashlib
import requests


LEVER_API = "https://api.lever.co/v0/postings/{slug}?mode=json"


def fetch_lever_jobs(company_slug: str) -> list[dict]:
    """Fetch all postings for a company from Lever's public API."""
    url = LEVER_API.format(slug=company_slug)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []


def parse_lever_job(posting: dict, company_name: str) -> dict:
    """Parse a Lever posting into our standard job dict."""
    title = posting.get("text", "")
    url = posting.get("hostedUrl") or posting.get("applyUrl", "")
    location = posting.get("categories", {}).get("location", "")
    team = posting.get("categories", {}).get("team", "")
    commitment = posting.get("categories", {}).get("commitment", "")

    # Build description from lists
    desc_parts = []
    for section in posting.get("lists", []):
        heading = section.get("text", "")
        content = section.get("content", "")
        if heading:
            desc_parts.append(f"## {heading}")
        if content:
            desc_parts.append(content)
    description = "\n\n".join(desc_parts)

    # Additional description from opening
    opening = posting.get("descriptionPlain") or posting.get("description", "")
    if opening:
        description = opening + "\n\n" + description

    posted_at = ""
    if posting.get("createdAt"):
        from datetime import datetime
        try:
            posted_at = datetime.fromtimestamp(posting["createdAt"] / 1000).isoformat()
        except Exception:
            pass

    # Hash for dedup
    raw = f"{company_name}_{title}_{url}"
    job_hash = hashlib.sha256(raw.encode()).hexdigest()

    if location and commitment:
        location = f"{location} ({commitment})"

    return {
        "company_name": company_name,
        "title": title,
        "url": url,
        "source": "lever",
        "location": location,
        "team": team,
        "description": description,
        "posted_at": posted_at,
        "hash": job_hash,
    }
