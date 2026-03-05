#!/usr/bin/env python3
"""
Board Scout — scrapes job boards using Crawl4AI (localhost:11234).
Targets Wellfound, Built In NYC, and Web3.career.

Usage:
    python board_scout.py             # live run, writes to DB
    python board_scout.py --dry-run   # print boards to scrape, no HTTP
    python board_scout.py --board wellfound   # scrape one board only
"""

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from utils import (
    complete_run,
    create_run,
    insert_job,
    job_exists,
    job_hash,
    load_config,
    score_job,
)

logger = logging.getLogger("scouts.board")

# ─── Crawl4AI ────────────────────────────────────────────────────────────────

CRAWL4AI_URL = "http://localhost:11234"
CRAWL_TIMEOUT = 45  # boards can be slow with JS rendering
RATE_LIMIT_DELAY = 2.0  # seconds between board crawls


def crawl_page(url: str) -> str:
    """
    Crawl a URL via local Crawl4AI instance.
    Returns markdown content, or empty string on failure.
    """
    payload = {
        "url": url,
        "priority": 8,
        "word_count_threshold": 100,
        "bypass_cache": True,
    }
    try:
        resp = requests.post(
            f"{CRAWL4AI_URL}/crawl",
            json=payload,
            timeout=CRAWL_TIMEOUT,
        )
        if resp.status_code == 200:
            result = resp.json()
            content = result.get("result", {}).get("markdown", "") or ""
            logger.debug("crawl_page[%s]: %d chars", url, len(content))
            return content
        else:
            logger.warning("crawl_page[%s]: HTTP %d", url, resp.status_code)
            return ""
    except requests.RequestException as e:
        logger.error("crawl_page[%s]: %s", url, e)
        return ""


def check_crawl4ai() -> bool:
    """Ping Crawl4AI health endpoint. Returns True if available."""
    try:
        resp = requests.get(f"{CRAWL4AI_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


# ─── Board Definitions ───────────────────────────────────────────────────────

@dataclass
class BoardConfig:
    name: str
    urls: list[str]
    parser: str  # which parse function to use


BOARDS: list[BoardConfig] = [
    BoardConfig(
        name="wellfound",
        urls=[
            "https://wellfound.com/jobs?role=business-development",
            "https://wellfound.com/jobs?role=partnerships",
        ],
        parser="wellfound",
    ),
    BoardConfig(
        name="builtinnyc",
        urls=[
            "https://www.builtinnyc.com/jobs/search?search=partnerships+director",
        ],
        parser="builtinnyc",
    ),
    BoardConfig(
        name="web3career",
        urls=[
            "https://web3.career/partnerships-jobs",
            "https://web3.career/business-development-jobs",
        ],
        parser="web3career",
    ),
]


# ─── Parsers ─────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """Strip extra whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def parse_wellfound(markdown: str) -> list[dict]:
    """
    Extract job listings from Wellfound markdown.
    Wellfound renders jobs as cards; typical markdown format:

      ## [Job Title](https://wellfound.com/jobs/...)
      Company Name · Location
    """
    jobs = []

    # Pattern: markdown link followed by company/location info
    # [Title](url) on its own line, then "Company · Location"
    pattern = re.compile(
        r"\[([^\]]+)\]\((https?://wellfound\.com/jobs/[^\)]+)\)"
        r"[^\n]*\n"
        r"([^\n•·\[\]]{3,80})",   # company + location line
        re.MULTILINE,
    )

    for m in pattern.finditer(markdown):
        title = _clean(m.group(1))
        url = m.group(2).split("?")[0]  # drop query params for cleaner dedup
        context_line = _clean(m.group(3))

        # Try to split "Company · Location" or "Company - Location"
        parts = re.split(r"[·\-–|]", context_line, maxsplit=1)
        company = _clean(parts[0]) if parts else ""
        location = _clean(parts[1]) if len(parts) > 1 else ""

        if title and url and len(title) > 3:
            jobs.append({
                "title": title,
                "company": company,
                "url": url,
                "location": location,
            })

    # Fallback: simpler link extraction if primary pattern yields nothing
    if not jobs:
        simple = re.compile(
            r"\[([^\]]{5,80})\]\((https?://wellfound\.com/jobs/[^\)]+)\)"
        )
        for m in simple.finditer(markdown):
            title = _clean(m.group(1))
            url = m.group(2)
            jobs.append({"title": title, "company": "", "url": url, "location": ""})

    logger.debug("wellfound parser: %d jobs extracted", len(jobs))
    return jobs


def parse_builtinnyc(markdown: str) -> list[dict]:
    """
    Extract job listings from Built In NYC markdown.
    Jobs typically appear as:

      ### [Job Title](https://www.builtinnyc.com/job/...)
      Company | Location
    """
    jobs = []

    pattern = re.compile(
        r"\[([^\]]+)\]\((https?://(?:www\.)?builtinnyc\.com/job[^\)]+)\)"
        r"[^\n]*\n?"
        r"([^\n\[\]]{0,100})",
        re.MULTILINE,
    )

    for m in pattern.finditer(markdown):
        title = _clean(m.group(1))
        url = m.group(2)
        context = _clean(m.group(3))

        parts = re.split(r"[|·\-–]", context, maxsplit=1)
        company = _clean(parts[0]) if parts else ""
        location = _clean(parts[1]) if len(parts) > 1 else "New York"

        if title and url and len(title) > 3:
            jobs.append({
                "title": title,
                "company": company,
                "url": url,
                "location": location,
            })

    # Fallback
    if not jobs:
        simple = re.compile(
            r"\[([^\]]{5,80})\]\((https?://(?:www\.)?builtinnyc\.com/job[^\)]+)\)"
        )
        for m in simple.finditer(markdown):
            jobs.append({
                "title": _clean(m.group(1)),
                "company": "",
                "url": m.group(2),
                "location": "New York",
            })

    logger.debug("builtinnyc parser: %d jobs extracted", len(jobs))
    return jobs


def parse_web3career(markdown: str) -> list[dict]:
    """
    Extract job listings from Web3.career markdown.
    Jobs typically appear as:

      [Job Title](https://web3.career/...) — Company — Location
    """
    jobs = []

    # Web3.career job URLs: /web3-job/... or /<slug>-<id>
    pattern = re.compile(
        r"\[([^\]]+)\]\((https?://web3\.career/[a-z0-9\-]+-\d+[^\)]*)\)"
        r"([^\n]{0,120})",
        re.MULTILINE,
    )

    for m in pattern.finditer(markdown):
        title = _clean(m.group(1))
        url = m.group(2)
        suffix = _clean(m.group(3))

        # Try to extract company/location from trailing text
        # Format is often " — Company — Location" or " | Company | Location"
        parts = re.split(r"[—\-–|·]", suffix)
        parts = [_clean(p) for p in parts if _clean(p)]
        company = parts[0] if parts else ""
        location = parts[1] if len(parts) > 1 else ""

        if title and url and len(title) > 3:
            jobs.append({
                "title": title,
                "company": company,
                "url": url,
                "location": location,
            })

    # Fallback: broader URL pattern
    if not jobs:
        simple = re.compile(
            r"\[([^\]]{5,80})\]\((https?://web3\.career/[^\)]+)\)"
        )
        for m in simple.finditer(markdown):
            jobs.append({
                "title": _clean(m.group(1)),
                "company": "",
                "url": m.group(2),
                "location": "",
            })

    logger.debug("web3career parser: %d jobs extracted", len(jobs))
    return jobs


# ─── Parser registry ──────────────────────────────────────────────────────────

PARSERS = {
    "wellfound": parse_wellfound,
    "builtinnyc": parse_builtinnyc,
    "web3career": parse_web3career,
}


# ─── Main Scout Logic ─────────────────────────────────────────────────────────

def run(dry_run: bool = False, board_filter: Optional[str] = None) -> dict:
    """
    Run the board scout across all configured boards.

    Returns: {jobs_found, jobs_new, jobs_skipped_dedup, jobs_skipped_low_score, errors}
    """
    config = load_config()
    min_score: int = config.get("min_store_score", 2)

    stats = {
        "jobs_found": 0,
        "jobs_new": 0,
        "jobs_skipped_dedup": 0,
        "jobs_skipped_low_score": 0,
        "errors": 0,
        "boards_scraped": 0,
    }

    boards = BOARDS
    if board_filter:
        boards = [b for b in BOARDS if b.name == board_filter.lower()]
        if not boards:
            logger.error("Unknown board '%s'. Valid: %s", board_filter, [b.name for b in BOARDS])
            sys.exit(1)

    if dry_run:
        print("\n🌐 Board Scout — DRY RUN (no HTTP requests)\n")
        print(f"{'─'*55}")
        print(f"  Total boards:    {len(boards)}")
        print(f"  Total URLs:      {sum(len(b.urls) for b in boards)}")
        print(f"  Crawl4AI URL:    {CRAWL4AI_URL}")
        print(f"  Min score:       {min_score}")
        print(f"{'─'*55}\n")
        for board in boards:
            print(f"📌 {board.name} ({len(board.urls)} URL(s)):")
            for url in board.urls:
                print(f"   {url}")
        print(f"\n✅ Dry run complete.\n")
        return stats

    # ── Live run ──────────────────────────────────────────────────────────────

    if not check_crawl4ai():
        logger.error(
            "Crawl4AI not reachable at %s — is it running? "
            "Start with: docker run -p 11234:11235 unclecode/crawl4ai",
            CRAWL4AI_URL,
        )
        stats["errors"] += 1
        return stats

    run_id = create_run("boards")
    logger.info("Board scout run_id=%s | %d boards", run_id, len(boards))

    for board in boards:
        parse_fn = PARSERS.get(board.parser)
        if not parse_fn:
            logger.error("No parser for board '%s'", board.name)
            continue

        for url in board.urls:
            logger.info("Crawling [%s] %s", board.name, url)
            try:
                markdown = crawl_page(url)
                if not markdown:
                    logger.warning("[%s] empty response for %s", board.name, url)
                    stats["errors"] += 1
                    continue

                raw_jobs = parse_fn(markdown)
                stats["boards_scraped"] += 1
                logger.info("[%s] parsed %d raw jobs from %s", board.name, len(raw_jobs), url)

                for raw in raw_jobs:
                    job_url = raw.get("url") or ""
                    job_title = raw.get("title") or ""
                    job_company = raw.get("company") or ""
                    job_location = raw.get("location") or ""

                    if not job_url or not job_title:
                        continue

                    stats["jobs_found"] += 1

                    score, keywords = score_job(job_title, "", job_location)

                    if score < min_score:
                        stats["jobs_skipped_low_score"] += 1
                        continue

                    if job_exists(job_url):
                        stats["jobs_skipped_dedup"] += 1
                        continue

                    job_dict = {
                        "id": job_hash(job_url),
                        "source": board.name,
                        "company": job_company,
                        "title": job_title,
                        "url": job_url,
                        "location": job_location,
                        "team": "",
                        "description": "",
                        "posted_date": "",
                        "match_score": score,
                        "match_keywords": keywords,
                    }

                    if insert_job(job_dict):
                        stats["jobs_new"] += 1
                        logger.info(
                            "  ✅ NEW  [%d] %s — %s @ %s",
                            score, board.name, job_title, job_company,
                        )
                    else:
                        stats["errors"] += 1

            except Exception as e:
                logger.error("[%s] unexpected error on %s: %s", board.name, url, e)
                stats["errors"] += 1

            time.sleep(RATE_LIMIT_DELAY)

    complete_run(run_id, stats)
    logger.info(
        "Board scout done | found=%d new=%d dedup=%d low_score=%d errors=%d",
        stats["jobs_found"], stats["jobs_new"],
        stats["jobs_skipped_dedup"], stats["jobs_skipped_low_score"],
        stats["errors"],
    )
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Board Scout — Crawl4AI job board scraper")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print boards and URLs; do not crawl",
    )
    parser.add_argument(
        "--board",
        metavar="NAME",
        help=f"Scrape a single board only. Valid: {[b.name for b in BOARDS]}",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    result = run(dry_run=args.dry_run, board_filter=args.board)

    if not args.dry_run:
        import json
        print(json.dumps(result, indent=2))
