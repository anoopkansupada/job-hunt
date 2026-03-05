#!/usr/bin/env python3
"""
Shared utilities: DB operations, job scoring, deduplication.
All scouts share this module.
"""

import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── Paths ───────────────────────────────────────────────────────────────────

SCOUTS_DIR = Path(__file__).parent
SCRAPER_DIR = SCOUTS_DIR.parent
DB_PATH = SCRAPER_DIR / "data" / "jobs.db"

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scouts.utils")

# ─── Scoring Keywords ────────────────────────────────────────────────────────

BOOST_KEYWORDS = [
    "partnerships",
    "ecosystem",
    "web3",
    "crypto",
    "blockchain",
    "defi",
    "growth",
    "bd",
    "business development",
    "protocol",
    "startup",
    "go-to-market",
]

ROLE_KEYWORDS = [
    "head of",
    "vp",
    "vice president",
    "director",
    "lead",
    "principal",
    "senior manager",
]

LOCATION_KEYWORDS = [
    "new york",
    "nyc",
    "remote",
    "hybrid",
]

EXCLUDE_KEYWORDS = [
    "junior",
    "entry level",
    "intern",
    "associate",
    "coordinator",
]

# ─── DB Bootstrap ────────────────────────────────────────────────────────────

CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,       -- SHA256[:16] of URL
    source          TEXT NOT NULL,          -- 'lever', 'greenhouse', 'wellfound', etc.
    company         TEXT,
    title           TEXT,
    url             TEXT UNIQUE NOT NULL,
    location        TEXT,
    team            TEXT,
    description     TEXT,
    posted_date     TEXT,
    match_score     INTEGER DEFAULT 0,
    match_keywords  TEXT,                   -- JSON array
    created_at      TEXT DEFAULT (datetime('now')),
    notified        INTEGER DEFAULT 0       -- 1 = Slack alert sent
);
"""

CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS scout_runs (
    run_id          TEXT PRIMARY KEY,
    run_type        TEXT NOT NULL,          -- 'ats', 'boards', 'full'
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT DEFAULT 'running', -- 'running', 'done', 'error'
    results         TEXT                    -- JSON blob
);
"""


def get_db() -> sqlite3.Connection:
    """Return a connection to the jobs DB, creating tables if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(CREATE_JOBS_TABLE)
    conn.execute(CREATE_RUNS_TABLE)
    conn.commit()
    return conn


# ─── Job Utilities ───────────────────────────────────────────────────────────

def job_hash(url: str) -> str:
    """Return first 16 chars of SHA256 of the URL — used as job ID."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def job_exists(url: str) -> bool:
    """True if a job with this URL already exists in the DB."""
    try:
        conn = get_db()
        cur = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,))
        exists = cur.fetchone() is not None
        conn.close()
        return exists
    except sqlite3.Error as e:
        logger.error("job_exists DB error: %s", e)
        return False


def insert_job(job_dict: dict) -> bool:
    """
    Insert a job into the DB. Returns True if newly inserted, False if duplicate.

    Expected keys: id, source, company, title, url, location, team,
                   description, posted_date, match_score, match_keywords
    """
    required = {"url", "source", "title"}
    if not required.issubset(job_dict):
        missing = required - job_dict.keys()
        logger.warning("insert_job: missing required fields %s", missing)
        return False

    # Ensure id is set
    if "id" not in job_dict or not job_dict["id"]:
        job_dict["id"] = job_hash(job_dict["url"])

    # Serialize match_keywords list to JSON string
    if isinstance(job_dict.get("match_keywords"), list):
        job_dict["match_keywords"] = json.dumps(job_dict["match_keywords"])

    try:
        conn = get_db()
        conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (id, source, company, title, url, location, team,
                 description, posted_date, match_score, match_keywords)
            VALUES
                (:id, :source, :company, :title, :url, :location, :team,
                 :description, :posted_date, :match_score, :match_keywords)
            """,
            {
                "id": job_dict.get("id"),
                "source": job_dict.get("source", "unknown"),
                "company": job_dict.get("company", ""),
                "title": job_dict.get("title", ""),
                "url": job_dict.get("url"),
                "location": job_dict.get("location", ""),
                "team": job_dict.get("team", ""),
                "description": job_dict.get("description", "")[:8000],  # cap size
                "posted_date": job_dict.get("posted_date", ""),
                "match_score": job_dict.get("match_score", 0),
                "match_keywords": job_dict.get("match_keywords", "[]"),
            },
        )
        inserted = conn.total_changes > 0
        conn.commit()
        conn.close()
        return inserted
    except sqlite3.Error as e:
        logger.error("insert_job DB error for '%s': %s", job_dict.get("url"), e)
        return False


def score_job(title: str, description: str, location: str = "") -> tuple[int, list[str]]:
    """
    Score a job posting based on keyword matching.

    Returns (score, matched_keywords) where:
      score  = count(BOOST_KEYWORDS in title+desc)
             + 2 if ROLE_KEYWORDS match in title
             + 1 if LOCATION_KEYWORDS match
             - 99 if EXCLUDE_KEYWORDS match in title (auto-exclude)
    """
    title_lower = title.lower()
    desc_lower = description.lower()
    location_lower = location.lower()
    combined = f"{title_lower} {desc_lower}"

    matched: list[str] = []
    score = 0

    # ① Exclude check (fast path)
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in title_lower:
            return -99, [f"EXCLUDED:{kw}"]

    # ② Boost keyword count
    for kw in BOOST_KEYWORDS:
        if kw.lower() in combined:
            score += 1
            matched.append(kw)

    # ③ Senior role in title (+2)
    for kw in ROLE_KEYWORDS:
        if kw.lower() in title_lower:
            score += 2
            matched.append(f"role:{kw}")
            break  # only count once

    # ④ Location match (+1)
    for kw in LOCATION_KEYWORDS:
        if kw.lower() in location_lower or kw.lower() in title_lower or kw.lower() in desc_lower:
            score += 1
            matched.append(f"location:{kw}")
            break  # only count once

    return score, matched


# ─── Run Tracking ────────────────────────────────────────────────────────────

def create_run(run_type: str) -> str:
    """Insert a new scout_runs row. Returns run_id."""
    run_id = hashlib.sha256(
        f"{run_type}-{datetime.utcnow().isoformat()}".encode()
    ).hexdigest()[:12]
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO scout_runs (run_id, run_type, started_at) VALUES (?, ?, ?)",
            (run_id, run_type, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error("create_run DB error: %s", e)
    return run_id


def complete_run(run_id: str, results: dict, status: str = "done") -> None:
    """Mark a scout_runs row as complete with results JSON."""
    try:
        conn = get_db()
        conn.execute(
            """
            UPDATE scout_runs
            SET completed_at = ?, status = ?, results = ?
            WHERE run_id = ?
            """,
            (
                datetime.utcnow().isoformat(),
                status,
                json.dumps(results),
                run_id,
            ),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error("complete_run DB error: %s", e)


# ─── Config Loader ───────────────────────────────────────────────────────────

def load_config() -> dict:
    """
    Load scraper config. Tries config.yaml first, falls back to config.example.yaml.
    """
    import yaml  # local import; pyyaml required

    candidates = [
        SCRAPER_DIR / "config.yaml",
        SCRAPER_DIR / "config.example.yaml",
    ]
    for path in candidates:
        if path.exists():
            logger.info("Loading config from %s", path)
            with open(path) as f:
                return yaml.safe_load(f) or {}

    raise FileNotFoundError(
        f"No config file found. Expected one of: {[str(p) for p in candidates]}"
    )
