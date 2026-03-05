"""
Job Hunt Pipeline -- SQLite database layer
Adapted from DataHive pipeline pattern.
"""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "jobs.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            lever_slug TEXT,
            greenhouse_slug TEXT,
            career_url TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER REFERENCES companies(id),
            company_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            location TEXT,
            team TEXT,
            description TEXT,
            posted_at TEXT,
            discovered_at TEXT DEFAULT (datetime('now')),
            match_score INTEGER,
            boost_score INTEGER DEFAULT 0,
            fit_score INTEGER,
            fit_reason TEXT,
            status TEXT DEFAULT 'new',
            notes TEXT,
            hash TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS seen_hashes (
            hash TEXT PRIMARY KEY,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER REFERENCES jobs(id),
            channel TEXT DEFAULT 'slack',
            sent_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS status_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER REFERENCES jobs(id),
            old_status TEXT,
            new_status TEXT,
            changed_at TEXT DEFAULT (datetime('now')),
            note TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_hash ON jobs(hash);
        CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name);
    """)
    conn.commit()
    conn.close()


def get_stats() -> dict:
    conn = get_conn()
    stats = {}
    stats["total_jobs"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    stats["new_jobs"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='new'").fetchone()[0]
    stats["companies"] = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    stats["high_score"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE match_score >= 5"
    ).fetchone()[0]
    stats["alerted"] = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]

    # Top sources
    rows = conn.execute(
        "SELECT source, COUNT(*) as n FROM jobs GROUP BY source ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        stats[f"source_{r['source']}"] = r["n"]

    conn.close()
    return stats


def upsert_company(name: str, lever_slug: str = None,
                   greenhouse_slug: str = None,
                   career_url: str = None) -> int:
    conn = get_conn()
    existing = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()
    if existing:
        company_id = existing["id"]
        updates = {}
        if lever_slug:
            updates["lever_slug"] = lever_slug
        if greenhouse_slug:
            updates["greenhouse_slug"] = greenhouse_slug
        if career_url:
            updates["career_url"] = career_url
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE companies SET {set_clause} WHERE id=?",
                list(updates.values()) + [company_id]
            )
            conn.commit()
    else:
        cur = conn.execute(
            "INSERT INTO companies (name, lever_slug, greenhouse_slug, career_url) VALUES (?,?,?,?)",
            (name, lever_slug, greenhouse_slug, career_url)
        )
        company_id = cur.lastrowid
        conn.commit()
    conn.close()
    return company_id


def insert_job(company_id: int, company_name: str, title: str, url: str,
               source: str, location: str, team: str, description: str,
               posted_at: str, match_score: int, boost_score: int,
               job_hash: str) -> int | None:
    """Insert a job if its hash doesn't exist. Returns job_id or None if dup."""
    conn = get_conn()
    existing = conn.execute("SELECT id FROM seen_hashes WHERE hash=?", (job_hash,)).fetchone()
    if existing:
        conn.execute("UPDATE seen_hashes SET last_seen=datetime('now') WHERE hash=?", (job_hash,))
        conn.commit()
        conn.close()
        return None

    conn.execute("INSERT INTO seen_hashes (hash) VALUES (?)", (job_hash,))
    cur = conn.execute(
        """INSERT INTO jobs (company_id, company_name, title, url, source,
           location, team, description, posted_at, match_score, boost_score, hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (company_id, company_name, title, url, source, location, team,
         description, posted_at, match_score, boost_score, job_hash)
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


def get_jobs(status: str = None, min_score: int = None, source: str = None,
             search: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_conn()
    clauses = []
    params = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if min_score is not None:
        clauses.append("match_score >= ?")
        params.append(min_score)
    if source:
        clauses.append("source=?")
        params.append(source)
    if search:
        clauses.append("(title LIKE ? OR company_name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"""SELECT * FROM jobs WHERE {where}
            ORDER BY match_score DESC, discovered_at DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_job(job_id: int, **kwargs):
    conn = get_conn()
    set_clause = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(
        f"UPDATE jobs SET {set_clause} WHERE id=?",
        list(kwargs.values()) + [job_id]
    )
    conn.commit()
    conn.close()


def append_status_log(job_id: int, new_status: str,
                      old_status: str = None, note: str = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO status_log (job_id, old_status, new_status, note) VALUES (?,?,?,?)",
        (job_id, old_status, new_status, note)
    )
    conn.commit()
    conn.close()
