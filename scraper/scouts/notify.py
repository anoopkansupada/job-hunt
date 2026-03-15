#!/usr/bin/env python3
"""
Slack Notifier — posts new high-score jobs to #job-hunt.

Called by orchestrator after each scout run.
Uses the Slack Bot Token (not webhook) so it goes through the existing bot.

Usage:
    python notify.py                # send any un-notified jobs >= min_score
    python notify.py --dry-run      # print what would be sent
    python notify.py --min-score 6  # override min score
"""

import argparse
import json
import logging
import os
import sqlite3
from pathlib import Path

import requests

from utils import get_db

logger = logging.getLogger("scouts.notify")

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = "#job-hunt"

MIN_ALERT_SCORE = 6   # default minimum match score to notify


# ─── Slack Sender ────────────────────────────────────────────────────────────

def post_to_slack(blocks: list, text: str, dry_run: bool = False) -> bool:
    if dry_run:
        print("─" * 60)
        print(f"[DRY RUN] Would post to {SLACK_CHANNEL}:")
        print(text)
        print("─" * 60)
        return True

    token = SLACK_TOKEN
    if not token:
        logger.error("SLACK_BOT_TOKEN not set — cannot notify")
        return False

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": SLACK_CHANNEL, "text": text, "blocks": blocks},
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        logger.error("Slack post failed: %s", data.get("error"))
        return False
    return True


# ─── Job Blocks Builder ──────────────────────────────────────────────────────

def build_job_blocks(jobs: list[dict]) -> tuple[list, str]:
    """Build Slack Block Kit message for a batch of jobs."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎯 {len(jobs)} New Job Match{'es' if len(jobs) != 1 else ''}"},
        },
        {"type": "divider"},
    ]

    for job in jobs[:10]:  # cap at 10 per message
        kw_str = ""
        try:
            kw_list = json.loads(job.get("match_keywords") or "[]")
            kw_str = "  ·  " + ", ".join(kw_list[:4]) if kw_list else ""
        except Exception:
            pass

        salary = job.get("salary_range") or ""
        location = job.get("location") or ""
        source = job.get("source") or ""
        score = job.get("match_score", 0)
        url = job.get("url", "")

        meta_parts = [p for p in [location, salary, source] if p]
        meta = "  ·  ".join(meta_parts)

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*<{url}|{job['title']}>*\n"
                    f"{job['company']}  ·  score {score}{kw_str}\n"
                    f"_{meta}_"
                ),
            },
        })

    if len(jobs) > 10:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"_...and {len(jobs) - 10} more in the DB_"},
        })

    blocks.append({"type": "divider"})

    text = f"🎯 {len(jobs)} new job match{'es' if len(jobs) != 1 else ''} — top: {jobs[0]['title']} @ {jobs[0]['company']}"
    return blocks, text


# ─── Main ────────────────────────────────────────────────────────────────────

def run(min_score: int = MIN_ALERT_SCORE, dry_run: bool = False) -> dict:
    """
    Find un-notified jobs above min_score, post to Slack, mark as notified.
    Returns stats dict.
    """
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, title, company, url, location, source, match_score, match_keywords, salary_range
        FROM jobs
        WHERE match_score >= ? AND notified = 0
        ORDER BY match_score DESC
        """,
        (min_score,),
    ).fetchall()

    jobs = [dict(r) for r in rows]
    conn.close()

    if not jobs:
        logger.info("No un-notified jobs above score %d", min_score)
        return {"notified": 0}

    logger.info("Found %d un-notified jobs to alert on", len(jobs))

    blocks, text = build_job_blocks(jobs)
    success = post_to_slack(blocks, text, dry_run=dry_run)

    if success and not dry_run:
        # Mark as notified
        conn = get_db()
        ids = [j["id"] for j in jobs]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE jobs SET notified = 1 WHERE id IN ({placeholders})", ids
        )
        conn.commit()
        conn.close()
        logger.info("Marked %d jobs as notified", len(jobs))

    return {"notified": len(jobs) if success else 0, "success": success}


def main():
    parser = argparse.ArgumentParser(description="Job Hunt Slack Notifier")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-score", type=int, default=MIN_ALERT_SCORE)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    stats = run(min_score=args.min_score, dry_run=args.dry_run)
    print(f"Notify complete: {stats}")


if __name__ == "__main__":
    main()
