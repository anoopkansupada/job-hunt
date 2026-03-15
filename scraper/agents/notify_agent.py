"""
notify_agent.py — Slack notification agent for job hunt pipeline.

Sends real-time match alerts + daily digests to #job-hunt Slack channel.

Usage:
    python -m agents.notify_agent --alert <job_id>   # single job alert
    python -m agents.notify_agent --digest            # 9am daily summary
    python -m agents.notify_agent --test              # send test message

Env vars:
    SLACK_WEBHOOK_URL  — Slack Incoming Webhook for #job-hunt
    JOB_DB_PATH        — override default DB path (default: ../data/jobs.db)
"""

import os
import sys
import json
import sqlite3
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path


# ── Config ───────────────────────────────────────────────────────────────────

DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
DB_PATH = os.getenv("JOB_DB_PATH", str(DEFAULT_DB))

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")

# Minimum fit_score to include in real-time alert
ALERT_MIN_SCORE = int(os.getenv("JOB_ALERT_MIN_SCORE", "6"))

# Optimizer URL for "Open in Optimizer" deeplinks
OPTIMIZER_URL = os.getenv("OPTIMIZER_URL", "http://localhost:3000")


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_job(job_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def fetch_new_since(hours: int = 24) -> list[dict]:
    """Jobs scraped in the last `hours` hours."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, source, company, title, url, location,
                   match_score, match_keywords, status, scraped_at
            FROM jobs
            WHERE scraped_at >= ?
            ORDER BY match_score DESC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_stats_since(hours: int = 24) -> dict:
    """Aggregate stats for the digest."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE scraped_at >= ?", (cutoff,)
        ).fetchone()[0]

        by_source = conn.execute(
            """
            SELECT source, COUNT(*) as count
            FROM jobs WHERE scraped_at >= ?
            GROUP BY source ORDER BY count DESC
            """,
            (cutoff,),
        ).fetchall()

        top_jobs = conn.execute(
            """
            SELECT id, company, title, match_score, source, location, url
            FROM jobs
            WHERE scraped_at >= ?
              AND match_score >= 6
            ORDER BY match_score DESC
            LIMIT 5
            """,
            (cutoff,),
        ).fetchall()

    return {
        "total": total,
        "by_source": [dict(r) for r in by_source],
        "top_jobs": [dict(r) for r in top_jobs],
    }


def record_alert(job_id: str, match_score: int) -> None:
    """Log alert to DB (avoids duplicate pings)."""
    import hashlib
    alert_id = hashlib.sha256(
        f"{job_id}:{datetime.utcnow().date()}".encode()
    ).hexdigest()[:16]

    with get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO alerts (id, job_id, alerted_at, channel, match_score)
                VALUES (?, ?, ?, 'slack', ?)
                """,
                (alert_id, job_id, datetime.utcnow().isoformat(), match_score),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # Already alerted today — skip


def was_already_alerted(job_id: str) -> bool:
    """Check if we already sent an alert for this job today."""
    today = datetime.utcnow().date().isoformat()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM alerts
            WHERE job_id = ?
              AND alerted_at >= ?
            LIMIT 1
            """,
            (job_id, today),
        ).fetchone()
    return row is not None


# ── Slack helpers ─────────────────────────────────────────────────────────────

def _post(text: str, blocks: list | None = None) -> bool:
    """
    POST to Slack webhook. Returns True on success.
    Gracefully degrades to console if no webhook configured.
    """
    if not SLACK_WEBHOOK:
        print(f"[notify] ⚠️  No SLACK_WEBHOOK_URL configured.")
        print(f"[notify] Message (not sent):\n{text[:300]}")
        return False

    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        r = requests.post(SLACK_WEBHOOK, json=payload, timeout=5)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[notify] ERROR posting to Slack: {e}")
        return False


def post_to_slack(message: dict, channel: str = "job-hunt") -> bool:
    """
    Post a message to Slack.
    
    Args:
        message: Dict with 'text' and optionally 'blocks' keys
        channel: Slack channel name (default: job-hunt)
        
    Returns:
        True if posted successfully
    """
    text = message.get("text", "")
    blocks = message.get("blocks")
    return _post(text, blocks)


def _score_badge(score: int) -> str:
    """Return a visual score indicator for Slack messages."""
    if score >= 9:
        return "🔥"
    elif score >= 7:
        return "⭐"
    elif score >= 5:
        return "✅"
    else:
        return "📋"


def _parse_keywords(raw: str | None, limit: int = 5) -> list[str]:
    """Safely parse match_keywords JSON string."""
    if not raw:
        return []
    try:
        kws = json.loads(raw)
        return kws[:limit] if isinstance(kws, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ── Notification functions ────────────────────────────────────────────────────

def send_new_match_alert(job: dict) -> bool:
    """
    Real-time alert for a high-score job match.
    Call this from the scout pipeline when a new job meets the threshold.

    Returns True if sent (or simulated), False on error.
    """
    title = job.get("title", "Unknown Role")
    company = job.get("company", "Unknown Co.")
    score = job.get("match_score", 0)
    source = job.get("source", "unknown")
    location = job.get("location") or "Location TBD"
    url = job.get("url", "")
    job_id = job.get("id", "")

    # Avoid double-alerting
    if job_id and was_already_alerted(job_id):
        print(f"[notify] Already alerted for {job_id} today — skipping")
        return False

    keywords = _parse_keywords(job.get("match_keywords"), limit=5)
    kw_str = ", ".join(keywords) if keywords else "—"
    badge = _score_badge(score)

    # Get Claude fit reason if available
    claude_reason = ""
    if job.get("notes"):
        try:
            notes = json.loads(job["notes"])
            if notes.get("reason"):
                claude_reason = f"\n_AI analysis: {notes['reason'][:120]}…_"
        except (json.JSONDecodeError, TypeError):
            pass

    text = (
        f"{badge} *New Job Match* — {title} @ {company}\n"
        f"Score: *{score}/10* | Source: {source.capitalize()} | {location}\n"
        f"{url}\n"
        f"\n"
        f"Keywords: {kw_str}"
        f"{claude_reason}\n"
        f"→ <{OPTIMIZER_URL}/jobs|Open in Job Board>  •  "
        f"<{OPTIMIZER_URL}/?jd_url={requests.utils.quote(url)}|Optimize Resume>"
    )

    success = _post(text)

    if success and job_id:
        record_alert(job_id, score)

    return success


def send_daily_digest() -> bool:
    """
    9am daily digest — summary of yesterday's discoveries.
    Intended to be called by cron: `python -m agents.notify_agent --digest`
    """
    today = datetime.utcnow().strftime("%B %-d")  # e.g. "March 4"
    stats = fetch_stats_since(hours=24)

    total = stats["total"]
    by_source = stats["by_source"]
    top_jobs = stats["top_jobs"]

    if total == 0:
        text = f"📋 *Job Hunt Digest — {today}*\nNo new jobs found in the last 24h. Pipeline may need a check."
        return _post(text)

    # Source breakdown
    source_lines = " | ".join(
        f"{r['source'].capitalize()}: {r['count']}" for r in by_source[:5]
    )

    # Top 5 jobs
    top_lines = ""
    for j in top_jobs:
        badge = _score_badge(j["match_score"])
        loc = f" — {j['location']}" if j.get("location") else ""
        top_lines += (
            f"  {badge} <{j['url']}|{j['title']} @ {j['company']}>"
            f" ({j['match_score']}/10){loc}\n"
        )

    text = (
        f"📋 *Job Hunt Daily Digest — {today}*\n"
        f"Found *{total}* new listings in the last 24h\n"
        f"Sources: {source_lines}\n"
        f"\n"
        f"⭐ *Top Matches:*\n"
        f"{top_lines}"
        f"\n"
        f"→ <{OPTIMIZER_URL}/jobs|Browse all jobs in INBOX>"
    )

    return _post(text)


def send_pipeline_alert(message: str, level: str = "info") -> bool:
    """
    System/ops alert for the pipeline (errors, run completions, etc.).

    level: 'info' | 'warn' | 'error'
    """
    icons = {"info": "ℹ️", "warn": "⚠️", "error": "🚨"}
    icon = icons.get(level, "ℹ️")
    text = f"{icon} *Job Hunt Pipeline* — {message}"
    return _post(text)


def send_test_message() -> bool:
    """Sends a test message to verify Slack webhook is working."""
    text = (
        "🔧 *Job Hunt Notify Agent — Test*\n"
        f"Webhook is configured. DB path: `{DB_PATH}`\n"
        f"Optimizer: {OPTIMIZER_URL}\n"
        f"Timestamp: {datetime.utcnow().isoformat()}"
    )
    return _post(text)


# ── Auto-alert new high-score jobs ────────────────────────────────────────────

def alert_new_high_score_jobs(min_score: int = ALERT_MIN_SCORE) -> int:
    """
    Check for recent high-score jobs that haven't been alerted yet.
    Call this after a scraper run to send real-time alerts.
    Returns count of alerts sent.
    """
    jobs = fetch_new_since(hours=24)
    alerted = 0

    for job in jobs:
        if job["match_score"] < min_score:
            continue
        if was_already_alerted(job["id"]):
            continue

        print(
            f"[notify] Alerting: {job['title']} @ {job['company']} "
            f"(score {job['match_score']})"
        )
        if send_new_match_alert(job):
            alerted += 1

    print(f"[notify] Sent {alerted} alerts (min_score={min_score})")
    return alerted


# ── CLI runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt Notify Agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--digest", action="store_true", help="Send daily digest")
    group.add_argument("--alert", metavar="JOB_ID", help="Alert on a specific job ID")
    group.add_argument(
        "--auto",
        action="store_true",
        help=f"Alert all new unalerted jobs with score ≥ {ALERT_MIN_SCORE}",
    )
    group.add_argument("--test", action="store_true", help="Send test message")
    parser.add_argument(
        "--min-score",
        type=int,
        default=ALERT_MIN_SCORE,
        help=f"Min score for --auto (default: {ALERT_MIN_SCORE})",
    )
    args = parser.parse_args()

    if args.test:
        ok = send_test_message()
        sys.exit(0 if ok else 1)

    elif args.digest:
        ok = send_daily_digest()
        sys.exit(0 if ok else 1)

    elif args.alert:
        job = fetch_job(args.alert)
        if not job:
            print(f"[notify] ERROR: Job '{args.alert}' not found in DB")
            sys.exit(1)
        ok = send_new_match_alert(job)
        sys.exit(0 if ok else 1)

    elif args.auto:
        count = alert_new_high_score_jobs(min_score=args.min_score)
        sys.exit(0 if count >= 0 else 1)
