"""
Pydantic models for Job Hunt Scout API.
All request/response bodies go here — DataHive pattern.
"""

from pydantic import BaseModel
from typing import List, Optional


# ── Response models ──────────────────────────────────────────────────────────

class Job(BaseModel):
    id: str
    source: str
    company: str
    title: str
    url: str
    location: Optional[str] = None
    team: Optional[str] = None
    salary_range: Optional[str] = None
    description: Optional[str] = None
    posted_date: Optional[str] = None
    created_at: Optional[str] = None
    match_score: int = 0
    match_keywords: Optional[str] = None   # JSON string, parsed by caller if needed
    status: str = "NEW"
    notes: Optional[str] = None


class JobSummary(BaseModel):
    """Lightweight listing view — no description."""
    id: str
    source: str
    company: str
    title: str
    url: str
    location: Optional[str] = None
    salary_range: Optional[str] = None
    posted_date: Optional[str] = None
    created_at: Optional[str] = None
    match_score: int = 0
    match_keywords: Optional[str] = None
    status: str = "NEW"


class Run(BaseModel):
    id: str
    run_type: str
    started_at: str
    finished_at: Optional[str] = None
    status: str = "RUNNING"
    jobs_found: int = 0
    jobs_new: int = 0
    jobs_alerted: int = 0
    error: Optional[str] = None


class Alert(BaseModel):
    id: str
    job_id: str
    alerted_at: str
    channel: str = "slack"
    match_score: Optional[int] = None


class Company(BaseModel):
    id: str
    name: str
    lever_slug: Optional[str] = None
    greenhouse_slug: Optional[str] = None
    career_page_url: Optional[str] = None
    active: int = 1
    last_checked: Optional[str] = None


# ── Request models ───────────────────────────────────────────────────────────

class UpdateStatusRequest(BaseModel):
    status: str   # NEW, VIEWED, APPLYING, APPLIED, REJECTED, ARCHIVED
    notes: Optional[str] = None


class TriggerRunRequest(BaseModel):
    run_type: str  # 'ats', 'boards', 'career_pages', 'full'


# ── Stats model ──────────────────────────────────────────────────────────────

class Stats(BaseModel):
    total_jobs: int
    new_today: int
    by_source: dict
    by_status: dict
    avg_match_score: float
    top_companies: List[dict]
    last_run: Optional[Run] = None
