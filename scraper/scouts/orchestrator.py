#!/usr/bin/env python3
"""
Scout Orchestrator — runs ATS and Board scouts, tracks run history.

Usage:
    python orchestrator.py                  # full run (ATS + boards)
    python orchestrator.py --type ats       # ATS only
    python orchestrator.py --type boards    # boards only
    python orchestrator.py --dry-run        # dry-run all scouts
    python orchestrator.py --status         # show last 5 runs from DB
"""

import argparse
import json
import logging
import sys
import threading
from datetime import datetime
from typing import Optional

from .utils import complete_run, create_run, get_db, load_config

logger = logging.getLogger("scouts.orchestrator")


# ─── Scout Runners ────────────────────────────────────────────────────────────

def run_ats_scout(dry_run: bool = False) -> dict:
    """Import and run the ATS scout. Returns its stats dict."""
    try:
        from . import ats_scout
        return ats_scout.run(dry_run=dry_run)
    except Exception as e:
        logger.error("ATS scout failed: %s", e)
        return {"error": str(e), "jobs_found": 0, "jobs_new": 0}


def run_board_scout(dry_run: bool = False) -> dict:
    """Import and run the Board scout. Returns its stats dict."""
    try:
        from . import board_scout
        return board_scout.run(dry_run=dry_run)
    except Exception as e:
        logger.error("Board scout failed: %s", e)
        return {"error": str(e), "jobs_found": 0, "jobs_new": 0}


# ─── Parallel Runner ─────────────────────────────────────────────────────────

def _run_parallel(run_type: str, dry_run: bool = False) -> dict:
    """
    Run ATS and board scouts in parallel using threads.
    Both write to the same SQLite DB (WAL mode handles concurrency).
    """
    results: dict = {}
    errors: list[str] = []

    def _ats():
        try:
            results["ats"] = run_ats_scout(dry_run=dry_run)
        except Exception as e:
            errors.append(f"ATS: {e}")
            results["ats"] = {"error": str(e)}

    def _boards():
        try:
            results["boards"] = run_board_scout(dry_run=dry_run)
        except Exception as e:
            errors.append(f"Boards: {e}")
            results["boards"] = {"error": str(e)}

    threads = []
    if run_type in ("ats", "full"):
        t = threading.Thread(target=_ats, name="ats-scout")
        threads.append(t)
    if run_type in ("boards", "full"):
        t = threading.Thread(target=_boards, name="board-scout")
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors:
        results["thread_errors"] = errors

    return results


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def run_all(
    run_type: str = "full",
    dry_run: bool = False,
    parallel: bool = True,
) -> dict:
    """
    Main orchestration function. Called by cron or CLI.

    Args:
        run_type: 'ats', 'boards', or 'full'
        dry_run:  if True, scouts print but don't hit APIs/crawl
        parallel: if True, run ATS + boards concurrently (default)

    Returns merged results dict.
    """
    valid_types = ("ats", "boards", "full")
    if run_type not in valid_types:
        raise ValueError(f"run_type must be one of {valid_types}, got '{run_type}'")

    logger.info(
        "Orchestrator start | type=%s dry_run=%s parallel=%s",
        run_type, dry_run, parallel,
    )

    if dry_run:
        print(f"\n🎯 Orchestrator — DRY RUN | type={run_type}\n{'─'*55}")
        results: dict = {}
        if run_type in ("ats", "full"):
            results["ats"] = run_ats_scout(dry_run=True)
        if run_type in ("boards", "full"):
            results["boards"] = run_board_scout(dry_run=True)
        return results

    run_id = create_run(run_type)

    try:
        if parallel and run_type == "full":
            logger.info("Running scouts in parallel (threads)")
            results = _run_parallel(run_type, dry_run=False)
        else:
            results = {}
            if run_type in ("ats", "full"):
                results["ats"] = run_ats_scout()
            if run_type in ("boards", "full"):
                results["boards"] = run_board_scout()

        # Aggregate summary
        total_new = sum(
            v.get("jobs_new", 0) for v in results.values() if isinstance(v, dict)
        )
        total_found = sum(
            v.get("jobs_found", 0) for v in results.values() if isinstance(v, dict)
        )
        results["_summary"] = {
            "run_id": run_id,
            "run_type": run_type,
            "total_found": total_found,
            "total_new": total_new,
            "completed_at": datetime.utcnow().isoformat(),
        }

        complete_run(run_id, results)
        logger.info(
            "Orchestrator done | run_id=%s total_found=%d total_new=%d",
            run_id, total_found, total_new,
        )

    except Exception as e:
        logger.error("Orchestrator fatal error: %s", e)
        complete_run(run_id, {"error": str(e)}, status="error")
        raise

    return results


# ─── Status Command ───────────────────────────────────────────────────────────

def show_status(limit: int = 10) -> None:
    """Print the last N scout runs from the DB."""
    try:
        conn = get_db()
        rows = conn.execute(
            """
            SELECT run_id, run_type, started_at, completed_at, status, results
            FROM scout_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()

        if not rows:
            print("No runs recorded yet.")
            return

        print(f"\n{'─'*70}")
        print(f"  Last {len(rows)} scout run(s):")
        print(f"{'─'*70}")
        for row in rows:
            results = {}
            try:
                results = json.loads(row["results"] or "{}")
            except Exception:
                pass

            summary = results.get("_summary", {})
            new = summary.get("total_new", "?")
            found = summary.get("total_found", "?")

            print(
                f"  {row['run_id']}  [{row['status']:<7}]  "
                f"{row['run_type']:<6}  "
                f"started={row['started_at'][:19]}  "
                f"found={found}  new={new}"
            )
        print(f"{'─'*70}\n")
    except Exception as e:
        logger.error("show_status error: %s", e)


def show_top_jobs(limit: int = 20, min_score: int = 5) -> None:
    """Print top-scoring jobs from the DB."""
    try:
        conn = get_db()
        rows = conn.execute(
            """
            SELECT title, company, location, match_score, match_keywords, source, url
            FROM jobs
            WHERE match_score >= ?
            ORDER BY match_score DESC, created_at DESC
            LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()
        conn.close()

        if not rows:
            print(f"No jobs with score >= {min_score} found.")
            return

        print(f"\n{'─'*80}")
        print(f"  Top {len(rows)} jobs (score >= {min_score}):")
        print(f"{'─'*80}")
        for row in rows:
            kw = ""
            try:
                kw = ", ".join(json.loads(row["match_keywords"] or "[]")[:4])
            except Exception:
                pass
            print(
                f"  [{row['match_score']:>2}] {row['title'][:45]:<45}  "
                f"{row['company'][:20]:<20}  {row['location'][:15]:<15}  "
                f"[{row['source']}]"
            )
            if kw:
                print(f"       ↳ keywords: {kw}")
            print(f"       ↳ {row['url'][:80]}")
        print(f"{'─'*80}\n")
    except Exception as e:
        logger.error("show_top_jobs error: %s", e)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scout Orchestrator — run job scouts and track results"
    )
    parser.add_argument(
        "--type",
        choices=["ats", "boards", "full"],
        default="full",
        help="Which scouts to run (default: full)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run; no HTTP requests",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Run scouts sequentially instead of parallel",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show last 10 runs and exit",
    )
    parser.add_argument(
        "--top-jobs",
        action="store_true",
        help="Show top-scoring jobs from DB and exit",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=5,
        help="Min score for --top-jobs display (default: 5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.status:
        show_status()
        sys.exit(0)

    if args.top_jobs:
        show_top_jobs(min_score=args.min_score)
        sys.exit(0)

    results = run_all(
        run_type=args.type,
        dry_run=args.dry_run,
        parallel=not args.sequential,
    )

    if not args.dry_run:
        # Send Slack alerts for new high-score jobs
        try:
            import notify
            notify_stats = notify.run(min_score=6, dry_run=False)
            results["notify"] = notify_stats
            logger.info("Slack notify: %s", notify_stats)
        except Exception as e:
            logger.warning("Notify failed (non-fatal): %s", e)
        print(json.dumps(results, indent=2))
