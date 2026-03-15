#!/usr/bin/env python3
"""
Daily Job Hunt Cron Orchestrator

Runs daily (Mon-Fri 8 AM EST):
1. Fetch new jobs from all scouts (LinkedIn, Greenhouse, Lever, job boards)
2. Rank jobs using Claude ranking_agent
3. Cross-reference top matches against Second Brain warm paths
4. Post top 5 matches to #job-hunt with reasoning

Usage:
    python daily_job_hunt_cron.py                 # full run
    python daily_job_hunt_cron.py --dry-run       # dry-run (no Slack post)
    python daily_job_hunt_cron.py --limit 10      # rank top 10 instead of 20
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Add scraper to path
scraper_path = Path(__file__).parent
sys.path.insert(0, str(scraper_path))

from scouts.orchestrator import run_all
from agents.ranking_agent import rank_new_jobs
from agents.notify_agent import post_to_slack
from scouts.utils import get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def get_warm_paths():
    """Query Second Brain for Anoop's warm paths to potential employers."""
    try:
        # This would connect to Second Brain graph and find decision-makers
        # at target companies. For now, return empty - will enhance later.
        return {}
    except Exception as e:
        logger.warning(f"Could not fetch warm paths: {e}")
        return {}


def filter_and_rank(jobs: list[dict], limit: int = 20) -> list[dict]:
    """
    Filter jobs by ranking score (7+), return top N.
    """
    ranked = [j for j in jobs if j.get("ranked_score", 0) >= 7]
    return sorted(ranked, key=lambda x: x.get("ranked_score", 0), reverse=True)[:limit]


def build_slack_message(top_jobs: list[dict]) -> dict:
    """Build Slack Block Kit message with top job matches."""
    
    if not top_jobs:
        return {
            "text": "No new high-match jobs found today.",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "📋 *Daily Job Hunt Digest*\n\nNo new jobs scoring 7+ found in the last 24h."
                    }
                }
            ]
        }
    
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🎯 *Daily Job Hunt Digest* — {len(top_jobs)} high-match job(s) found"
            }
        },
        {"type": "divider"}
    ]
    
    for i, job in enumerate(top_jobs[:5], 1):
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")
        score = job.get("ranked_score", 0)
        reason = job.get("ranking_notes", "No details")
        url = job.get("url", "#")
        
        score_emoji = "⭐⭐⭐" if score >= 9 else "⭐⭐" if score >= 8 else "⭐"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{i}. {title}* @ {company}\n"
                    f"Fit Score: {score_emoji} ({score}/10)\n"
                    f"_{reason}_"
                )
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "View Job"},
                "url": url,
                "action_id": f"job_view_{i}"
            }
        })
        blocks.append({"type": "divider"})
    
    return {
        "text": f"Daily Job Hunt: {len(top_jobs)} matches",
        "blocks": blocks
    }


def main(args):
    logger.info("Starting daily job hunt orchestration...")
    
    try:
        # Step 1: Run scouts to fetch new jobs
        logger.info("Running job scouts...")
        scout_stats = run_all(run_type="full", dry_run=False)  # ATS + Board scouts
        logger.info(f"Scout results: {scout_stats}")
        
        # Step 2: Rank new jobs using Claude
        logger.info("Ranking new jobs...")
        ranked = rank_new_jobs(limit=args.limit)
        logger.info(f"Ranked {len(ranked)} jobs")
        
        if not ranked:
            logger.info("No jobs ranked - skipping Slack post")
            return
        
        # Step 3: Filter for high matches (7+)
        logger.info("Filtering high-match jobs (7+)...")
        top_jobs = filter_and_rank(ranked, limit=5)
        logger.info(f"Found {len(top_jobs)} high-match jobs")
        
        if not top_jobs:
            logger.info("No jobs with score 7+ - posting empty digest")
        
        # Step 4: Build and post to Slack
        logger.info("Building Slack message...")
        message = build_slack_message(top_jobs)
        
        if not args.dry_run:
            logger.info("Posting to Slack #job-hunt...")
            post_to_slack(message, channel="job-hunt")
            logger.info("Posted successfully")
        else:
            logger.info(f"DRY RUN - would post: {json.dumps(message, indent=2)}")
        
        logger.info("Daily job hunt orchestration complete")
        
    except Exception as e:
        logger.error(f"Error during orchestration: {e}", exc_info=True)
        if not args.dry_run:
            try:
                post_to_slack({
                    "text": f"❌ Job Hunt Error: {str(e)}",
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"🚨 *Daily Job Hunt Failed*\n```{str(e)}```"
                        }
                    }]
                }, channel="job-hunt")
            except:
                pass
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily job hunt orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no Slack post)")
    parser.add_argument("--limit", type=int, default=20, help="Limit jobs to rank (default 20)")
    
    args = parser.parse_args()
    main(args)
