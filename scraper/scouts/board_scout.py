#!/usr/bin/env python3
"""
Board Scout — scrapes LinkedIn, Indeed, Glassdoor via JobSpy.
Replaces the Crawl4AI-based Wellfound/BuiltInNYC approach.

Runs multiple targeted searches for Anoop's Web3/BD profile,
deduplicates by URL, scores each job, and inserts into the DB.

Usage:
    python board_scout.py               # live run, writes to DB
    python board_scout.py --dry-run     # print results, no DB writes
    python board_scout.py --term "VP BD crypto"  # single custom search
    python board_scout.py --boards linkedin       # one board only
    python board_scout.py --days 3     # limit to jobs posted in last N days

Requirements:
    pip install python-jobspy  (NOT 'jobspy' — different package)
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Optional

try:
    from jobspy import scrape_jobs
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False

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

# ─── Target searches (Anoop's Web3/BD profile) ────────────────────────────────

DEFAULT_SEARCH_TERMS = [
    "head of partnerships web3 crypto",
    "VP business development blockchain",
    "director of ecosystem crypto defi",
    "VP growth web3 fintech",
    "head of BD crypto protocol",
    "director partnerships crypto",
    "VP partnerships web3 NYC",
    "ecosystem lead blockchain protocol",
]

DEFAULT_BOARDS = ["linkedin", "indeed", "glassdoor"]

DEFAULT_HOURS_OLD = 168   # 7 days — catch everything on first run
RESULTS_PER_TERM  = 25   # per board per search term

# ─── Source normalizer ────────────────────────────────────────────────────────

BOARD_LABEL = {
    "linkedin":     "linkedin",
    "indeed":       "indeed",
    "glassdoor":    "glassdoor",
    "zip_recruiter":"ziprecruiter",
    "google":       "google",
}


# ─── Main runner ──────────────────────────────────────────────────────────────

def run(
    dry_run: bool = False,
    boards: Optional[list] = None,
    search_terms: Optional[list] = None,
    hours_old: int = DEFAULT_HOURS_OLD,
) -> dict:
    """
    Run all board searches, dedup, score, and insert into DB.
    Returns stats dict: {jobs_found, jobs_new, jobs_skipped, errors}
    """
    if not JOBSPY_AVAILABLE:
        logger.error(
            "python-jobspy not installed. Run: pip install python-jobspy"
        )
        return {"error": "python-jobspy not installed", "jobs_found": 0, "jobs_new": 0}

    if boards is None:
        boards = DEFAULT_BOARDS
    if search_terms is None:
        search_terms = DEFAULT_SEARCH_TERMS

    run_id = create_run("boards") if not dry_run else "dry-run"

    stats = {
        "jobs_found": 0,
        "jobs_new": 0,
        "jobs_skipped": 0,
        "jobs_excluded": 0,
        "search_errors": 0,
        "by_term": {},
        "by_board": {},
    }

    seen_urls: set[str] = set()   # in-memory dedup across search terms

    for term in search_terms:
        logger.info("Searching: '%s' on %s", term, boards)
        try:
            df = scrape_jobs(
                site_name=boards,
                search_term=term,
                results_wanted=RESULTS_PER_TERM,
                hours_old=hours_old,
                verbose=0,
            )
        except Exception as e:
            logger.warning("Search failed for '%s': %s", term, e)
            stats["search_errors"] += 1
            stats["by_term"][term] = {"error": str(e)}
            continue

        term_new = 0
        term_found = len(df)

        for _, row in df.iterrows():
            url = str(row.get("job_url", "") or "").strip()
            if not url:
                continue

            # ① In-memory cross-term dedup
            if url in seen_urls:
                stats["jobs_skipped"] += 1
                continue
            seen_urls.add(url)

            # ② DB dedup
            if not dry_run and job_exists(url):
                stats["jobs_skipped"] += 1
                continue

            title    = str(row.get("title", "") or "").strip()
            company  = str(row.get("company", "") or "").strip()
            location = str(row.get("location", "") or "").strip()
            desc     = str(row.get("description", "") or "").strip()
            source   = BOARD_LABEL.get(str(row.get("site", "")), "board")

            # ③ Score
            score, keywords = score_job(title, desc, location)
            if score < 0:
                stats["jobs_excluded"] += 1
                continue

            # ④ Build salary string
            salary_range = _build_salary(row)

            # ⑤ Posted date
            posted = ""
            raw_date = row.get("date_posted")
            if raw_date and str(raw_date) not in ("nan", "None", ""):
                posted = str(raw_date)

            job = {
                "id":             job_hash(url),
                "source":         source,
                "company":        company,
                "title":          title,
                "url":            url,
                "location":       location,
                "team":           str(row.get("job_function", "") or ""),
                "description":    desc[:8000],
                "posted_date":    posted,
                "match_score":    score,
                "match_keywords": json.dumps(keywords),
                # Extra fields (may not be in base CREATE_JOBS_TABLE — no-op if absent)
                "salary_range":   salary_range,
                "is_remote":      _bool_val(row.get("is_remote")),
                "job_level":      str(row.get("job_level", "") or ""),
            }

            if dry_run:
                _print_job(job, keywords)
            else:
                inserted = insert_job(job)
                if inserted:
                    stats["jobs_new"] += 1
                    term_new += 1
                    # Track by board
                    stats["by_board"][source] = stats["by_board"].get(source, 0) + 1

            stats["jobs_found"] += 1

        stats["by_term"][term] = {"found": term_found, "new": term_new}
        logger.info("  '%s' → %d found, %d new", term, term_found, term_new)

    if not dry_run:
        complete_run(run_id, stats)

    return stats


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _build_salary(row) -> str:
    """Format min/max salary into a readable string, e.g. '$180k–$220k/yr'."""
    try:
        mn = row.get("min_amount")
        mx = row.get("max_amount")
        interval = str(row.get("interval", "") or "").lower()

        def fmt(v):
            if v is None or str(v) in ("nan", "None", ""):
                return None
            n = float(v)
            return f"${int(n / 1000)}k" if n >= 1000 else f"${int(n)}"

        lo, hi = fmt(mn), fmt(mx)
        if not lo and not hi:
            return ""
        period = "/yr" if "year" in interval or "annual" in interval else (f"/{interval}" if interval else "")
        if lo and hi:
            return f"{lo}–{hi}{period}"
        return f"{lo or hi}{period}"
    except Exception:
        return ""


def _bool_val(v) -> int:
    """Convert various truthy forms to 0/1."""
    if v is None:
        return 0
    return 1 if str(v).lower() in ("true", "1", "yes") else 0


def _print_job(job: dict, keywords: list) -> None:
    print(
        f"  [{job['source']:12s}] {job['company']:30s} | {job['title'][:50]}"
        f" | score={job['match_score']} | {job['salary_range'] or 'no salary'}"
        f" | keywords={keywords[:4]}"
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Board Scout via JobSpy")
    parser.add_argument("--dry-run", action="store_true", help="Print results, no DB writes")
    parser.add_argument("--boards", nargs="+", default=None,
                        help="Boards to search (linkedin indeed glassdoor zip_recruiter)")
    parser.add_argument("--term", help="Single custom search term (overrides defaults)")
    parser.add_argument("--days", type=int, default=7,
                        help="Max age of postings in days (default: 7)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    search_terms = [args.term] if args.term else None

    stats = run(
        dry_run=args.dry_run,
        boards=args.boards,
        search_terms=search_terms,
        hours_old=args.days * 24,
    )

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Board Scout complete:")
    print(f"  Found:    {stats['jobs_found']}")
    print(f"  New:      {stats['jobs_new']}")
    print(f"  Skipped:  {stats['jobs_skipped']} (duplicates)")
    print(f"  Excluded: {stats['jobs_excluded']} (score < 0)")
    print(f"  Errors:   {stats['search_errors']} search failures")
    if stats.get("by_board"):
        print(f"  By board: {stats['by_board']}")


if __name__ == "__main__":
    main()
