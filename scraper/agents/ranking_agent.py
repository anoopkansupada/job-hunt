"""
ranking_agent.py — Claude-powered job ranker for Anoop's job hunt.

Fetches the top N new jobs from the last 24h, sends them to Claude
(claude-haiku-4-5) for deep ranking based on Anoop's Web3/BD profile,
then writes the fit_score back to jobs.ranked_score + notes in the DB.

Usage:
    python -m agents.ranking_agent             # rank top 20 new jobs
    python -m agents.ranking_agent --limit 10  # rank top 10

Env vars:
    ANTHROPIC_API_KEY  — required
    JOB_DB_PATH        — override default DB path (default: ../data/jobs.db)
"""

import anthropic
import sqlite3
import json
import os
import sys
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────

# Default DB path relative to this file: scraper/data/jobs.db
DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
DB_PATH = os.getenv("JOB_DB_PATH", str(DEFAULT_DB))

RANKING_PROMPT = """You are helping Anoop Kansupada find his next senior role in Web3/BD partnerships.

## Anoop's Profile
- 10+ years Web3/blockchain partnerships & ecosystem development
- Background: Corp Dev, BD at crypto/DeFi protocols, exchange partnerships
- Currently targeting: Head of Partnerships, VP BD, Director of Ecosystem, VP Growth
- Sweet spot: Series B-D crypto/Web3/fintech companies, NYC or Remote
- Core strengths: deal structuring, ecosystem building, protocol partnerships, VC relationships
- Target compensation: $200K–$350K total (base + equity)
- Hard pass: roles below Director-level, pure sales roles, non-Web3/non-fintech companies

## Your Task
Rate each job 1–10 on fit for Anoop. Be honest and differentiated — use the full 1–10 range.

Scoring guide:
- 9–10: Near-perfect match. Web3 ecosystem, senior title, NYC/remote, strong stage fit
- 7–8: Strong match. Missing one dimension (e.g., not Web3 but great BD scope)
- 5–6: Decent match. Some relevant signals but notable gaps
- 3–4: Weak match. Wrong seniority, wrong industry, or limited scope
- 1–2: Bad fit. Entry-level, sales-only, totally off-profile

Return a JSON array ONLY — no markdown, no extra text:
[
  {{"job_id": "abc123", "fit_score": 8, "reason": "Senior ecosystem role at Series C DeFi protocol. NYC-based, strong protocol partnerships scope. Missing equity info but strong org-level fit."}},
  ...
]

## Jobs to Rank
{jobs_json}
"""


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Return a SQLite connection. Row factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_new_jobs(limit: int = 20) -> list[dict]:
    """
    Fetch top unranked NEW jobs from the last 24h,
    ordered by match_score DESC (keyword score as pre-filter),
    limited to `limit` rows.
    """
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, source, company, title, url, location,
                   salary_range, description, posted_date, created_at,
                   match_score, match_keywords, status
            FROM jobs
            WHERE status = 'NEW'
              AND created_at >= ?
            ORDER BY match_score DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def update_job_ranking(job_id: str, fit_score: int, reason: str) -> None:
    """Write Claude's fit_score + reason back into the DB."""
    # We store fit_score in match_score (overrides keyword score with AI score)
    # and the reason in notes (JSON object for structured storage)
    note_payload = json.dumps(
        {
            "ranked_by": "claude",
            "fit_score": fit_score,
            "reason": reason,
            "ranked_at": datetime.utcnow().isoformat(),
        }
    )
    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET match_score = ?, notes = ? WHERE id = ?",
            (fit_score, note_payload, job_id),
        )
        conn.commit()


# ── Claude ranking ────────────────────────────────────────────────────────────

def build_jobs_payload(jobs: list[dict]) -> str:
    """Trim jobs to the fields Claude needs — keep tokens low."""
    trimmed = []
    for j in jobs:
        # Truncate description to 400 chars to stay within haiku token budget
        desc = (j.get("description") or "")[:400]
        trimmed.append(
            {
                "job_id": j["id"],
                "title": j["title"],
                "company": j["company"],
                "location": j.get("location") or "Unknown",
                "salary_range": j.get("salary_range") or "Not listed",
                "source": j["source"],
                "description_preview": desc,
            }
        )
    return json.dumps(trimmed, indent=2)


def call_claude(jobs: list[dict]) -> list[dict]:
    """
    Call claude-haiku-4-5 with the ranking prompt.
    Returns a list of {job_id, fit_score, reason} dicts.
    Raises ValueError if the response can't be parsed.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    jobs_json = build_jobs_payload(jobs)
    prompt = RANKING_PROMPT.format(jobs_json=jobs_json)

    print(f"[ranking] Sending {len(jobs)} jobs to Claude haiku-4-5…")

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if Claude adds them
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        rankings = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"[ranking] Claude returned invalid JSON: {e}\n---\n{raw}")

    if not isinstance(rankings, list):
        raise ValueError(f"[ranking] Expected JSON array, got: {type(rankings)}")

    return rankings


# ── Main entrypoint ───────────────────────────────────────────────────────────

def rank_new_jobs(limit: int = 20) -> list[dict]:
    """
    Rank the top `limit` new jobs from the last 24h using Claude.

    Steps:
    1. Fetch top NEW jobs (last 24h) ordered by keyword match_score DESC
    2. Send to Claude for deep ranking (1–10 fit score)
    3. Write scores + reasons back to DB
    4. Return ranked list sorted by fit_score DESC

    Returns the enriched job dicts with `fit_score` and `fit_reason` added.
    """
    print(f"[ranking] Fetching up to {limit} new jobs from last 24h…")

    jobs = fetch_new_jobs(limit=limit)

    if not jobs:
        print("[ranking] No new jobs found in the last 24h. Nothing to rank.")
        return []

    print(f"[ranking] Found {len(jobs)} new jobs. Ranking with Claude…")

    try:
        rankings = call_claude(jobs)
    except ValueError as e:
        print(f"[ranking] ERROR: {e}")
        return []

    # Build lookup for fast update
    rank_map = {r["job_id"]: r for r in rankings if "job_id" in r}

    updated = []
    skipped = 0

    for job in jobs:
        jid = job["id"]
        ranking = rank_map.get(jid)

        if not ranking:
            print(f"[ranking] WARNING: No ranking returned for job {jid} — skipping")
            skipped += 1
            continue

        fit_score = int(ranking.get("fit_score", 0))
        reason = ranking.get("reason", "")

        update_job_ranking(jid, fit_score, reason)

        enriched = {
            **job,
            "fit_score": fit_score,
            "fit_reason": reason,
        }
        updated.append(enriched)

    # Sort by fit_score DESC for caller convenience
    updated.sort(key=lambda x: x["fit_score"], reverse=True)

    print(
        f"[ranking] Done. {len(updated)} ranked, {skipped} skipped. "
        f"Top: {updated[0]['title']} @ {updated[0]['company']} "
        f"(fit: {updated[0]['fit_score']}/10)" if updated else "[ranking] Done. 0 ranked."
    )

    return updated


# ── CLI runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rank new jobs with Claude")
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max jobs to rank (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + prompt-build only — no Claude call, no DB writes",
    )
    args = parser.parse_args()

    if args.dry_run:
        jobs = fetch_new_jobs(limit=args.limit)
        print(f"[dry-run] Would rank {len(jobs)} jobs:")
        for j in jobs:
            print(f"  • {j['title']} @ {j['company']} (score: {j['match_score']})")
        if jobs:
            print("\n[dry-run] Prompt preview (truncated):")
            print(build_jobs_payload(jobs[:3]))
        sys.exit(0)

    results = rank_new_jobs(limit=args.limit)

    print("\n── Top Ranked Jobs ──────────────────────────────────────────")
    for i, job in enumerate(results[:10], 1):
        print(
            f"{i:2}. [{job['fit_score']}/10] {job['title']} @ {job['company']}"
            f" ({job.get('location', 'Remote?')})"
        )
        print(f"    {job.get('fit_reason', '')[:100]}")
