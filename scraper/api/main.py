#!/usr/bin/env python3
"""
Job Hunt Scout — API Backend
FastAPI routes for: jobs, runs, alerts, stats
Port: 8001   DB: ../data/jobs.db

DataHive pattern: raw sqlite3, Pydantic models, no ORM.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import uuid
import os
import sys
from datetime import datetime, timezone
from typing import Optional, List

# Ensure api/ is on path so `models` resolves whether imported or run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    Job, JobSummary, Run, Stats,
    UpdateStatusRequest, TriggerRunRequest,
)

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Job Hunt Scout API",
    version="1.0.0",
    description="Backend for the job discovery pipeline — discovers, scores, and tracks job postings.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB path relative to api/ directory
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "..", "data", "jobs.db")
SCHEMA_PATH = os.path.join(_HERE, "..", "db", "schema.sql")


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Run schema.sql to create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()
    conn = get_conn()
    conn.executescript(schema)
    conn.commit()
    conn.close()


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — confirms DB is reachable."""
    try:
        conn = get_conn()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": DB_PATH, "ts": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Jobs ─────────────────────────────────────────────────────────────────────

@app.get("/jobs", response_model=dict)
def list_jobs(
    status: Optional[str] = None,
    source: Optional[str] = None,
    min_score: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    List jobs with optional filters.
    Filters: status (NEW/VIEWED/APPLYING/APPLIED/REJECTED/ARCHIVED),
             source (lever/greenhouse/linkedin/indeed/wellfound/career_page),
             min_score (0-12).
    Sorted by match_score DESC, scraped_at DESC.
    """
    conn = get_conn()
    cursor = conn.cursor()

    conditions = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if source:
        conditions.append("source = ?")
        params.append(source)
    if min_score is not None:
        conditions.append("match_score >= ?")
        params.append(min_score)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cursor.execute(
        f"""
        SELECT id, source, company, title, url, location,
               salary_range, posted_date, scraped_at,
               match_score, match_keywords, status
        FROM jobs
        {where}
        ORDER BY match_score DESC, scraped_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    rows = cursor.fetchall()

    # Total count for pagination
    cursor.execute(f"SELECT COUNT(*) FROM jobs {where}", params)
    total = cursor.fetchone()[0]
    conn.close()

    jobs = [
        JobSummary(
            id=r["id"],
            source=r["source"],
            company=r["company"],
            title=r["title"],
            url=r["url"],
            location=r["location"],
            salary_range=r["salary_range"],
            posted_date=r["posted_date"],
            scraped_at=r["scraped_at"],
            match_score=r["match_score"],
            match_keywords=r["match_keywords"],
            status=r["status"],
        )
        for r in rows
    ]

    return {"total": total, "limit": limit, "offset": offset, "jobs": [j.dict() for j in jobs]}


@app.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str):
    """Full job detail including description and notes."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return Job(**dict(row))


@app.post("/jobs/{job_id}/status")
def update_job_status(job_id: str, body: UpdateStatusRequest):
    """
    Update job status and optionally set notes.
    Valid statuses: NEW, VIEWED, APPLYING, APPLIED, REJECTED, ARCHIVED
    """
    valid_statuses = {"NEW", "VIEWED", "APPLYING", "APPLIED", "REJECTED", "ARCHIVED"}
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Must be one of: {', '.join(sorted(valid_statuses))}",
        )

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if body.notes is not None:
        cursor.execute(
            "UPDATE jobs SET status = ?, notes = ? WHERE id = ?",
            (body.status, body.notes, job_id),
        )
    else:
        cursor.execute(
            "UPDATE jobs SET status = ? WHERE id = ?",
            (body.status, job_id),
        )

    conn.commit()
    conn.close()

    return {"job_id": job_id, "status": body.status, "updated_at": datetime.now(timezone.utc).isoformat()}


# ── Runs ─────────────────────────────────────────────────────────────────────

@app.get("/runs", response_model=dict)
def list_runs():
    """List the last 20 scout runs, newest first."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT 20"
    )
    rows = cursor.fetchall()
    conn.close()

    runs = [Run(**dict(r)) for r in rows]
    return {"count": len(runs), "runs": [r.dict() for r in runs]}


@app.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str):
    """Single run detail."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return Run(**dict(row))


@app.post("/runs/trigger")
def trigger_run(body: TriggerRunRequest):
    """
    Register a new scout run in the DB and return its ID.
    The actual scraping is handled by the scout agents — this just
    creates the run record so agents can update it as they go.
    Valid run_types: ats, boards, career_pages, full
    """
    valid_types = {"ats", "boards", "career_pages", "full"}
    if body.run_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid run_type '{body.run_type}'. Must be one of: {', '.join(sorted(valid_types))}",
        )

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO runs (id, run_type, started_at, status)
        VALUES (?, ?, ?, 'RUNNING')
        """,
        (run_id, body.run_type, started_at),
    )
    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "run_type": body.run_type,
        "started_at": started_at,
        "status": "RUNNING",
        "message": f"Run {run_id} registered. Scouts will pick this up.",
    }


# ── Stats ────────────────────────────────────────────────────────────────────

@app.get("/stats")
def get_stats():
    """
    Dashboard stats:
    - total jobs, new today
    - breakdown by source
    - breakdown by status
    - avg match score
    - top 5 companies by job count
    - last completed run
    """
    conn = get_conn()
    cursor = conn.cursor()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Total + new today
    cursor.execute("SELECT COUNT(*) FROM jobs")
    total_jobs = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM jobs WHERE DATE(scraped_at) = ?", (today,))
    new_today = cursor.fetchone()[0]

    # By source
    cursor.execute("SELECT source, COUNT(*) as cnt FROM jobs GROUP BY source ORDER BY cnt DESC")
    by_source = {r["source"]: r["cnt"] for r in cursor.fetchall()}

    # By status
    cursor.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status ORDER BY cnt DESC")
    by_status = {r["status"]: r["cnt"] for r in cursor.fetchall()}

    # Avg match score
    cursor.execute("SELECT AVG(match_score) FROM jobs")
    avg_row = cursor.fetchone()[0]
    avg_match_score = round(avg_row, 2) if avg_row else 0.0

    # Top 5 companies
    cursor.execute(
        """
        SELECT company, COUNT(*) as cnt
        FROM jobs
        GROUP BY company
        ORDER BY cnt DESC
        LIMIT 5
        """
    )
    top_companies = [{"company": r["company"], "count": r["cnt"]} for r in cursor.fetchall()]

    # Last completed run
    cursor.execute(
        "SELECT * FROM runs WHERE status = 'COMPLETE' ORDER BY finished_at DESC LIMIT 1"
    )
    last_run_row = cursor.fetchone()
    last_run = Run(**dict(last_run_row)).dict() if last_run_row else None

    conn.close()

    return {
        "total_jobs": total_jobs,
        "new_today": new_today,
        "by_source": by_source,
        "by_status": by_status,
        "avg_match_score": avg_match_score,
        "top_companies": top_companies,
        "last_run": last_run,
    }


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
