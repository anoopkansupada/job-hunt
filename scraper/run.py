#!/usr/bin/env python3
"""
Job Hunt Discovery Pipeline -- Orchestrator
Adapted from DataHive BD Pipeline pattern.

Usage:
  python3 run.py --stats                          # Show pipeline stats
  python3 run.py --all [--limit N]                # Run all stages
  python3 run.py --stage discover [--limit N]     # Lever + Greenhouse fetch
  python3 run.py --stage filter                   # Re-score unscored jobs
  python3 run.py --dry-run --all                  # Discover + score, don't store
  python3 run.py --company "Stripe"               # Single company

Stages:
  1. discover  -> fetch jobs from Lever + Greenhouse APIs
  2. filter    -> score/re-score jobs against config criteria
  3. notify    -> alert on high-scoring matches (future: Slack)
"""
import sys
import time
import argparse
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import get_conn, get_stats, init_db, upsert_company, insert_job, update_job
from filter import score_job, passes_threshold, load_config
from scrapers.lever_api import fetch_lever_jobs, parse_lever_job
from scrapers.greenhouse_api import fetch_greenhouse_jobs, parse_greenhouse_job


def print_stats():
    """Print current pipeline stats."""
    stats = get_stats()
    print("\nJob Hunt Pipeline Stats")
    print("=" * 40)
    for k, v in stats.items():
        print(f"  {k:<20}: {v}")

    conn = get_conn()
    # Score distribution
    rows = conn.execute("""
        SELECT
            CASE
                WHEN match_score >= 8 THEN 'hot (8+)'
                WHEN match_score >= 5 THEN 'good (5-7)'
                WHEN match_score >= 2 THEN 'maybe (2-4)'
                ELSE 'skip (0-1)'
            END as tier,
            COUNT(*) as n
        FROM jobs
        GROUP BY tier
        ORDER BY tier
    """).fetchall()
    if rows:
        print("\nScore Distribution:")
        for r in rows:
            print(f"  {r['tier']:<20}: {r['n']}")

    # Recent high-score jobs
    top = conn.execute("""
        SELECT company_name, title, match_score, boost_score
        FROM jobs WHERE match_score >= 5
        ORDER BY discovered_at DESC LIMIT 10
    """).fetchall()
    if top:
        print("\nRecent High-Score Jobs:")
        for r in top:
            boost = f" +{r['boost_score']}b" if r['boost_score'] else ""
            print(f"  [{r['match_score']}/12{boost}] {r['title']} @ {r['company_name']}")

    conn.close()


def stage_discover(config: dict, limit: int = None, company_name: str = None,
                   dry_run: bool = False):
    """Stage 1: Fetch jobs from Lever + Greenhouse APIs."""
    companies = config.get("companies", [])
    if company_name:
        companies = [c for c in companies if c["name"].lower() == company_name.lower()]
        if not companies:
            print(f"  Company '{company_name}' not found in config")
            return

    total_new = 0
    total_seen = 0
    total_skipped = 0

    for i, comp in enumerate(companies):
        name = comp["name"]
        print(f"  [{i+1}/{len(companies)}] {name}", end=" ... ", flush=True)

        # Ensure company exists in DB
        company_id = upsert_company(
            name=name,
            lever_slug=comp.get("lever_slug"),
            greenhouse_slug=comp.get("greenhouse_slug"),
            career_url=comp.get("career_page"),
        )

        jobs = []

        # Lever
        if comp.get("lever_slug"):
            raw = fetch_lever_jobs(comp["lever_slug"])
            for posting in raw:
                jobs.append(parse_lever_job(posting, name))

        # Greenhouse
        if comp.get("greenhouse_slug"):
            raw = fetch_greenhouse_jobs(comp["greenhouse_slug"])
            for posting in raw:
                jobs.append(parse_greenhouse_job(posting, name))

        if not jobs:
            print("0 postings")
            time.sleep(0.3)
            continue

        # Score and insert
        new = 0
        seen = 0
        skipped = 0
        for job in jobs:
            match_score, boost_score = score_job(job, config)
            should_store, should_alert = passes_threshold(match_score, config)

            if not should_store:
                skipped += 1
                continue

            if dry_run:
                if should_alert:
                    print(f"\n    [DRY] {job['title']} score={match_score} +{boost_score}b", end="")
                new += 1
                continue

            job_id = insert_job(
                company_id=company_id,
                company_name=name,
                title=job["title"],
                url=job["url"],
                source=job["source"],
                location=job["location"],
                team=job["team"],
                description=job["description"],
                posted_at=job["posted_at"],
                match_score=match_score,
                boost_score=boost_score,
                job_hash=job["hash"],
            )
            if job_id:
                new += 1
            else:
                seen += 1

        total_new += new
        total_seen += seen
        total_skipped += skipped
        print(f"{len(jobs)} postings, {new} new, {seen} seen, {skipped} below threshold")
        time.sleep(0.5)

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n  {prefix}Discovery complete: {total_new} new, {total_seen} seen, {total_skipped} skipped")


def stage_filter(config: dict, limit: int = 100):
    """Stage 2: Re-score jobs that haven't been scored yet (or re-score all)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE match_score IS NULL LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    if not rows:
        print("  All jobs already scored")
        return

    print(f"  Scoring {len(rows)} jobs")
    for i, row in enumerate(rows):
        r = dict(row)
        match_score, boost_score = score_job(r, config)
        update_job(r["id"], match_score=match_score, boost_score=boost_score)

    print(f"  Scored {len(rows)} jobs")


def stage_notify(config: dict, limit: int = 50):
    """Stage 3: Alert on new high-scoring jobs."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT j.* FROM jobs j
        LEFT JOIN alerts a ON j.id = a.job_id
        WHERE a.id IS NULL
        AND j.match_score >= ?
        ORDER BY j.match_score DESC
        LIMIT ?
    """, (config.get("min_alert_score", 5), limit)).fetchall()
    conn.close()

    if not rows:
        print("  No new jobs to alert on")
        return

    print(f"\n  New matches to alert ({len(rows)}):")
    for r in rows:
        r = dict(r)
        boost = f" +{r['boost_score']}b" if r.get('boost_score') else ""
        print(f"    [{r['match_score']}/12{boost}] {r['title']} @ {r['company_name']}")
        print(f"      {r['url']}")

    webhook = config.get("slack_webhook", "")
    if not webhook:
        print("\n  Slack webhook not configured -- skipping alerts")
        print("  Set slack_webhook in config.yaml to enable")
        return

    # TODO: Send Slack alerts when webhook is configured
    print(f"\n  Would send {len(rows)} alerts to Slack")


def run_all(config: dict, limit: int = None, company_name: str = None,
            dry_run: bool = False):
    """Run all stages in order."""
    print("Running full job discovery pipeline\n")
    print("[Stage 1/3] Discover")
    stage_discover(config, limit=limit, company_name=company_name, dry_run=dry_run)
    if not dry_run:
        print("\n[Stage 2/3] Filter")
        stage_filter(config, limit=limit or 100)
        print("\n[Stage 3/3] Notify")
        stage_notify(config)
    print("\nPipeline complete.")
    print_stats()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt Discovery Pipeline")
    parser.add_argument("--stats", action="store_true", help="Show pipeline stats")
    parser.add_argument("--all", action="store_true", help="Run all stages")
    parser.add_argument("--stage", choices=["discover", "filter", "notify"],
                        help="Run specific stage")
    parser.add_argument("--company", type=str, help="Process single company by name")
    parser.add_argument("--limit", type=int, default=None, help="Max items to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview without storing")
    args = parser.parse_args()

    init_db()

    config = load_config()

    if args.stats or (not args.all and not args.stage and not args.company):
        print_stats()
    elif args.all:
        run_all(config, limit=args.limit, company_name=args.company, dry_run=args.dry_run)
    elif args.stage == "discover":
        stage_discover(config, limit=args.limit, company_name=args.company,
                       dry_run=args.dry_run)
    elif args.stage == "filter":
        stage_filter(config, limit=args.limit or 100)
    elif args.stage == "notify":
        stage_notify(config)
    elif args.company:
        run_all(config, company_name=args.company, dry_run=args.dry_run)
