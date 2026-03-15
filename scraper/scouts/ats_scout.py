#!/usr/bin/env python3
"""
ATS Scout — queries Lever and Greenhouse public APIs for target companies.
No authentication required for either API.

Usage:
    python ats_scout.py             # live run, writes to DB
    python ats_scout.py --dry-run   # print companies + slugs, no HTTP
"""

import argparse
import logging
import sys
import time
from typing import Any, Optional

import requests

from .utils import (
    complete_run,
    create_run,
    insert_job,
    is_us_relevant,
    job_exists,
    job_hash,
    load_config,
    score_job,
)

logger = logging.getLogger("scouts.ats")

# ─── API Constants ────────────────────────────────────────────────────────────

LEVER_BASE = "https://api.lever.co/v0/postings/{slug}?mode=json"
GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

REQUEST_TIMEOUT = 15  # seconds
RATE_LIMIT_DELAY = 0.3  # seconds between API calls (be polite)

# ─── Lever ────────────────────────────────────────────────────────────────────


def fetch_lever_jobs(slug: str) -> list[dict]:
    """Fetch all job postings from Lever for the given company slug."""
    url = LEVER_BASE.format(slug=slug)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("Lever[%s]: unexpected response shape", slug)
            return []
        return data
    except requests.RequestException as e:
        logger.error("Lever[%s] fetch error: %s", slug, e)
        return []


def parse_lever_job(raw: dict, company_name: str) -> Optional[dict]:
    """Normalise a raw Lever job object into our schema."""
    try:
        title = raw.get("text") or ""
        url = raw.get("hostedUrl") or ""
        if not url:
            return None

        categories = raw.get("categories") or {}
        location = categories.get("location") or categories.get("allLocations", [""])[0] if isinstance(categories.get("allLocations"), list) else ""
        team = categories.get("team") or categories.get("department") or ""
        description = raw.get("descriptionPlain") or ""

        # posted date — Lever gives epoch ms
        created_at_ms = raw.get("createdAt")
        posted_date = ""
        if created_at_ms:
            from datetime import datetime
            posted_date = datetime.utcfromtimestamp(created_at_ms / 1000).strftime("%Y-%m-%d")

        score, keywords = score_job(title, description, location)

        return {
            "id": job_hash(url),
            "source": "lever",
            "company": company_name,
            "title": title,
            "url": url,
            "location": location,
            "team": team,
            "description": description,
            "posted_date": posted_date,
            "match_score": score,
            "match_keywords": keywords,
        }
    except Exception as e:
        logger.error("parse_lever_job error: %s — raw: %s", e, str(raw)[:200])
        return None


# ─── Greenhouse ───────────────────────────────────────────────────────────────


def fetch_greenhouse_jobs(slug: str) -> list[dict]:
    """Fetch all job postings from Greenhouse for the given company slug."""
    url = GREENHOUSE_BASE.format(slug=slug)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs") if isinstance(data, dict) else []
        if not isinstance(jobs, list):
            logger.warning("Greenhouse[%s]: unexpected response shape", slug)
            return []
        return jobs
    except requests.RequestException as e:
        logger.error("Greenhouse[%s] fetch error: %s", slug, e)
        return []


def parse_greenhouse_job(raw: dict, company_name: str) -> Optional[dict]:
    """Normalise a raw Greenhouse job object into our schema."""
    try:
        title = raw.get("title") or ""
        url = raw.get("absolute_url") or ""
        if not url:
            return None

        # Location can be a dict or a list of dicts
        loc_raw = raw.get("location") or {}
        if isinstance(loc_raw, dict):
            location = loc_raw.get("name") or ""
        elif isinstance(loc_raw, list) and loc_raw:
            location = loc_raw[0].get("name") or "" if isinstance(loc_raw[0], dict) else str(loc_raw[0])
        else:
            location = str(loc_raw)

        # Department / team from departments array
        departments = raw.get("departments") or []
        team = departments[0].get("name") if departments and isinstance(departments[0], dict) else ""

        description = raw.get("content") or ""
        # Greenhouse returns HTML; strip basic tags for storage
        import re
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()

        # posted date
        updated_at = raw.get("updated_at") or ""
        posted_date = updated_at[:10] if updated_at else ""

        score, keywords = score_job(title, description, location)

        return {
            "id": job_hash(url),
            "source": "greenhouse",
            "company": company_name,
            "title": title,
            "url": url,
            "location": location,
            "team": team,
            "description": description,
            "posted_date": posted_date,
            "match_score": score,
            "match_keywords": keywords,
        }
    except Exception as e:
        logger.error("parse_greenhouse_job error: %s — raw: %s", e, str(raw)[:200])
        return None


# ─── Main Scout Logic ─────────────────────────────────────────────────────────


def run(dry_run: bool = False) -> dict:
    """
    Run the ATS scout against all configured companies.

    Returns: {jobs_found, jobs_new, jobs_skipped_dedup, errors}
    """
    config = load_config()
    companies: list[dict] = config.get("companies", [])
    min_score: int = config.get("min_store_score", 2)

    stats = {
        "jobs_found": 0,
        "jobs_new": 0,
        "jobs_skipped_dedup": 0,
        "jobs_skipped_low_score": 0,
        "jobs_skipped_location": 0,
        "errors": 0,
        "companies_queried": 0,
    }

    # Within-run dedup: (company, normalized_title) → skip regional dupes
    seen_this_run: set[tuple[str, str]] = set()

    lever_companies = [(c["name"], c["lever_slug"]) for c in companies if "lever_slug" in c]
    gh_companies = [(c["name"], c["greenhouse_slug"]) for c in companies if "greenhouse_slug" in c]

    if dry_run:
        print("\n🔍 ATS Scout — DRY RUN (no HTTP requests)\n")
        print(f"{'─'*55}")
        print(f"  Total companies: {len(companies)}")
        print(f"  Lever:           {len(lever_companies)}")
        print(f"  Greenhouse:      {len(gh_companies)}")
        print(f"  Min score:       {min_score}")
        print(f"{'─'*55}\n")

        print("📌 Lever companies:")
        for name, slug in lever_companies:
            print(f"   {name:<25}  slug={slug}")
            print(f"   → {LEVER_BASE.format(slug=slug)}")

        print("\n📌 Greenhouse companies:")
        for name, slug in gh_companies:
            print(f"   {name:<25}  slug={slug}")
            print(f"   → {GREENHOUSE_BASE.format(slug=slug)}")

        print(f"\n✅ Dry run complete. Would query {len(lever_companies) + len(gh_companies)} endpoints.\n")
        return stats

    # ── Live run ──────────────────────────────────────────────────────────────

    run_id = create_run("ats")
    logger.info("ATS scout run_id=%s | %d Lever + %d GH companies",
                run_id, len(lever_companies), len(gh_companies))

    def _process_job(parsed: Optional[dict]) -> str:
        """Returns 'new', 'dedup', 'low_score', 'location', or 'error'."""
        if not parsed:
            return "error"
        stats["jobs_found"] += 1

        # ① Location filter — skip non-US postings
        if not is_us_relevant(parsed.get("location", "")):
            stats["jobs_skipped_location"] += 1
            return "location"

        if parsed["match_score"] < min_score:
            return "low_score"

        # ② Within-run title dedup — skip same role posted for multiple regions
        title_key = (parsed["company"].lower(), parsed["title"].lower().strip())
        if title_key in seen_this_run:
            stats["jobs_skipped_dedup"] += 1
            return "dedup"
        seen_this_run.add(title_key)

        # ③ DB-level URL dedup
        if job_exists(parsed["url"]):
            stats["jobs_skipped_dedup"] += 1
            return "dedup"

        if insert_job(parsed):
            return "new"
        return "error"

    # ── Lever ─────────────────────────────────────────────────────────────────
    for company_name, slug in lever_companies:
        logger.info("Lever → %s (%s)", company_name, slug)
        try:
            raw_jobs = fetch_lever_jobs(slug)
            stats["companies_queried"] += 1
            for raw in raw_jobs:
                parsed = parse_lever_job(raw, company_name)
                outcome = _process_job(parsed)
                if outcome == "new":
                    stats["jobs_new"] += 1
                    logger.info("  ✅ NEW  [%d] %s — %s", parsed["match_score"], company_name, parsed["title"])
                elif outcome == "dedup":
                    stats["jobs_skipped_dedup"] += 1
                elif outcome == "low_score":
                    stats["jobs_skipped_low_score"] += 1
                elif outcome == "error":
                    stats["errors"] += 1
        except Exception as e:
            logger.error("Lever[%s] unexpected error: %s", slug, e)
            stats["errors"] += 1
        time.sleep(RATE_LIMIT_DELAY)

    # ── Greenhouse ────────────────────────────────────────────────────────────
    for company_name, slug in gh_companies:
        logger.info("Greenhouse → %s (%s)", company_name, slug)
        try:
            raw_jobs = fetch_greenhouse_jobs(slug)
            stats["companies_queried"] += 1
            for raw in raw_jobs:
                parsed = parse_greenhouse_job(raw, company_name)
                outcome = _process_job(parsed)
                if outcome == "new":
                    stats["jobs_new"] += 1
                    logger.info("  ✅ NEW  [%d] %s — %s", parsed["match_score"], company_name, parsed["title"])
                elif outcome == "dedup":
                    stats["jobs_skipped_dedup"] += 1
                elif outcome == "low_score":
                    stats["jobs_skipped_low_score"] += 1
                elif outcome == "error":
                    stats["errors"] += 1
        except Exception as e:
            logger.error("Greenhouse[%s] unexpected error: %s", slug, e)
            stats["errors"] += 1
        time.sleep(RATE_LIMIT_DELAY)

    complete_run(run_id, stats)
    logger.info(
        "ATS scout done | found=%d new=%d dedup=%d low_score=%d errors=%d",
        stats["jobs_found"], stats["jobs_new"],
        stats["jobs_skipped_dedup"], stats["jobs_skipped_low_score"],
        stats["errors"],
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATS Scout — Lever + Greenhouse job fetcher")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print companies and API endpoints; do not make HTTP requests",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    result = run(dry_run=args.dry_run)

    if not args.dry_run:
        import json
        print(json.dumps(result, indent=2))
