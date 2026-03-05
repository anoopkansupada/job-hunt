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

  python3 run.py --apply JOB_ID                   # Start application for a job
  python3 run.py --update-app APP_ID STATUS        # Update application status
  python3 run.py --apps                            # Show all applications
  python3 run.py --apps --status interviewing      # Filter by status
  python3 run.py --add-contact "Company" "Name" "Title"  # Add a hiring contact
  python3 run.py --contacts                        # List all contacts
  python3 run.py --contacts --company "Stripe"     # Contacts at a company
  python3 run.py --pipeline                        # Full funnel view

Stages:
  1. discover  -> fetch jobs from Lever + Greenhouse APIs
  2. filter    -> score/re-score jobs against config criteria
  3. notify    -> alert on high-scoring matches (future: Slack)

Application statuses:
  interested -> preparing -> applied -> phone_screen -> interviewing ->
  final_round -> offer -> accepted | rejected | withdrawn | ghosted
"""
import sys
import time
import argparse
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import (get_conn, get_stats, init_db, upsert_company, insert_job, update_job,
               upsert_contact, get_contacts, create_application, update_application,
               get_applications, get_app_stats)
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


def cmd_apply(job_id: int):
    """Create an application from a discovered job."""
    conn = get_conn()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not job:
        print(f"  Job #{job_id} not found")
        return
    job = dict(job)

    # Check if already applied
    conn = get_conn()
    existing = conn.execute(
        "SELECT id, status FROM applications WHERE job_id=?", (job_id,)
    ).fetchone()
    conn.close()
    if existing:
        print(f"  Already tracking: application #{existing['id']} (status: {existing['status']})")
        return

    app_id = create_application(job_id=job_id)
    print(f"  Application #{app_id} created")
    print(f"  {job['title']} @ {job['company_name']}")
    print(f"  Score: {job['match_score']}/12 | {job['url']}")
    print(f"  Status: interested")
    print(f"\n  Next: python3 run.py --update-app {app_id} preparing")


VALID_STATUSES = ["interested", "preparing", "applied", "phone_screen",
                  "interviewing", "final_round", "offer", "accepted",
                  "rejected", "withdrawn", "ghosted"]


def cmd_update_app(app_id: int, new_status: str):
    """Update an application's status."""
    from datetime import datetime

    if new_status not in VALID_STATUSES:
        print(f"  Invalid status: '{new_status}'")
        print(f"  Valid: {', '.join(VALID_STATUSES)}")
        return

    conn = get_conn()
    app = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    conn.close()
    if not app:
        print(f"  Application #{app_id} not found")
        return

    old_status = app["status"]
    updates = {"status": new_status}
    if new_status == "applied" and not app["applied_at"]:
        updates["applied_at"] = datetime.now().isoformat()
    if new_status in ("phone_screen", "interviewing", "final_round", "offer") and not app["response_at"]:
        updates["response_at"] = datetime.now().isoformat()

    update_application(app_id, **updates)
    print(f"  Application #{app_id}: {old_status} -> {new_status}")
    print(f"  {app['title']} @ {app['company_name']}")


def cmd_apps(status: str = None):
    """Show applications."""
    apps = get_applications(status=status, limit=100)
    if not apps:
        print("  No applications found")
        return

    # Group by status
    by_status = {}
    for a in apps:
        by_status.setdefault(a["status"], []).append(a)

    status_order = ["interested", "preparing", "applied", "phone_screen",
                    "interviewing", "final_round", "offer", "accepted",
                    "rejected", "withdrawn", "ghosted"]

    print(f"\nApplications ({len(apps)} total)")
    print("=" * 60)
    for s in status_order:
        group = by_status.get(s, [])
        if not group:
            continue
        print(f"\n  [{s.upper()}] ({len(group)})")
        for a in group:
            ref = f" (referral)" if a.get("referral_contact_id") else ""
            date = ""
            if s == "applied" and a.get("applied_at"):
                date = f" | applied {a['applied_at'][:10]}"
            elif a.get("next_step_date"):
                date = f" | next: {a['next_step_date']}"
            print(f"    #{a['id']} {a['title']} @ {a['company_name']}{ref}{date}")
            if a.get("notes"):
                print(f"       note: {a['notes']}")


def cmd_add_contact(company_name: str, name: str, title: str = None,
                    linkedin_url: str = None, email: str = None):
    """Add a hiring manager contact."""
    contact_id = upsert_contact(
        company_name=company_name, name=name, title=title,
        linkedin_url=linkedin_url, email=email
    )
    print(f"  Contact #{contact_id}: {name}")
    if title:
        print(f"  Title: {title}")
    print(f"  Company: {company_name}")


def cmd_contacts(company_name: str = None):
    """List contacts."""
    contacts = get_contacts(company_name=company_name, limit=100)
    if not contacts:
        print("  No contacts found")
        return

    print(f"\nContacts ({len(contacts)})")
    print("=" * 60)
    current_company = None
    for c in sorted(contacts, key=lambda x: x["company_name"] or ""):
        if c["company_name"] != current_company:
            current_company = c["company_name"]
            print(f"\n  {current_company}")
        title = f" -- {c['title']}" if c.get("title") else ""
        li = f" | {c['linkedin_url']}" if c.get("linkedin_url") else ""
        status = f" [{c['outreach_status']}]" if c["outreach_status"] != "not_contacted" else ""
        print(f"    #{c['id']} {c['name']}{title}{li}{status}")


def cmd_pipeline():
    """Full funnel view: discovery -> applications -> outcomes."""
    stats = get_stats()
    app_stats = get_app_stats()

    print("\nJob Hunt Pipeline -- Full Funnel")
    print("=" * 50)

    # Discovery
    print(f"\n  DISCOVERY")
    print(f"    Jobs found:     {stats.get('total_jobs', 0)}")
    print(f"    High score 5+:  {stats.get('high_score', 0)}")

    # Applications funnel
    total_apps = sum(v for k, v in app_stats.items()
                     if k not in ("total_contacts", "outreach_sent", "outreach_replied"))
    active = sum(app_stats.get(s, 0) for s in
                 ["interested", "preparing", "applied", "phone_screen",
                  "interviewing", "final_round", "offer"])
    applied = sum(app_stats.get(s, 0) for s in
                  ["applied", "phone_screen", "interviewing", "final_round",
                   "offer", "accepted", "rejected", "ghosted"])
    responses = sum(app_stats.get(s, 0) for s in
                    ["phone_screen", "interviewing", "final_round", "offer", "accepted"])

    print(f"\n  APPLICATIONS")
    print(f"    Total tracked:  {total_apps}")
    print(f"    Active:         {active}")
    print(f"    Applied:        {applied}")
    print(f"    Got response:   {responses}")
    if applied > 0:
        print(f"    Response rate:  {responses/applied*100:.0f}%")

    # Breakdown
    for status in ["interested", "preparing", "applied", "phone_screen",
                   "interviewing", "final_round", "offer", "accepted",
                   "rejected", "withdrawn", "ghosted"]:
        ct = app_stats.get(status, 0)
        if ct > 0:
            print(f"      {status:<16}: {ct}")

    # Contacts
    print(f"\n  NETWORKING")
    print(f"    Contacts:       {app_stats.get('total_contacts', 0)}")
    print(f"    Outreach sent:  {app_stats.get('outreach_sent', 0)}")
    print(f"    Replies:        {app_stats.get('outreach_replied', 0)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt Discovery Pipeline")
    parser.add_argument("--stats", action="store_true", help="Show pipeline stats")
    parser.add_argument("--all", action="store_true", help="Run all stages")
    parser.add_argument("--stage", choices=["discover", "filter", "notify"],
                        help="Run specific stage")
    parser.add_argument("--company", type=str, help="Process single company by name")
    parser.add_argument("--limit", type=int, default=None, help="Max items to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview without storing")
    # Application tracking
    parser.add_argument("--apply", type=int, metavar="JOB_ID",
                        help="Start tracking an application for a job")
    parser.add_argument("--update-app", nargs=2, metavar=("APP_ID", "STATUS"),
                        help="Update application status")
    parser.add_argument("--apps", action="store_true", help="Show all applications")
    parser.add_argument("--status", type=str, help="Filter applications by status")
    parser.add_argument("--pipeline", action="store_true", help="Full funnel view")
    # Contacts
    parser.add_argument("--add-contact", nargs="+", metavar="ARG",
                        help="Add contact: COMPANY NAME [TITLE] [LINKEDIN_URL]")
    parser.add_argument("--contacts", action="store_true", help="List contacts")
    args = parser.parse_args()

    init_db()

    config = load_config()

    if args.apply:
        cmd_apply(args.apply)
    elif args.update_app:
        cmd_update_app(int(args.update_app[0]), args.update_app[1])
    elif args.apps:
        cmd_apps(status=args.status)
    elif args.pipeline:
        cmd_pipeline()
    elif args.add_contact:
        parts = args.add_contact
        if len(parts) < 2:
            print("  Usage: --add-contact COMPANY NAME [TITLE] [LINKEDIN_URL]")
        else:
            cmd_add_contact(
                company_name=parts[0], name=parts[1],
                title=parts[2] if len(parts) > 2 else None,
                linkedin_url=parts[3] if len(parts) > 3 else None,
            )
    elif args.contacts:
        cmd_contacts(company_name=args.company)
    elif args.stats or (not args.all and not args.stage and not args.company):
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
