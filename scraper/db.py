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
            domain TEXT,
            lever_slug TEXT,
            greenhouse_slug TEXT,
            ats_platform TEXT,
            ats_slug TEXT,
            ats_api_url TEXT,
            career_url TEXT,
            resolved_at TEXT,
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

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER REFERENCES companies(id),
            company_name TEXT,
            name TEXT NOT NULL,
            title TEXT,
            linkedin_url TEXT,
            email TEXT,
            source TEXT DEFAULT 'manual',
            connection_degree INTEGER,
            mutual_connections TEXT,
            warm_intro_viable INTEGER DEFAULT 0,
            notes TEXT,
            outreach_status TEXT DEFAULT 'not_contacted',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER REFERENCES jobs(id),
            company_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            status TEXT DEFAULT 'interested'
                CHECK(status IN ('interested','preparing','applied',
                                 'phone_screen','interviewing','final_round',
                                 'offer','accepted','rejected','withdrawn','ghosted')),
            applied_at TEXT,
            resume_version TEXT,
            cover_letter INTEGER DEFAULT 0,
            referral_contact_id INTEGER REFERENCES contacts(id),
            response_at TEXT,
            next_step TEXT,
            next_step_date TEXT,
            salary_range TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS outreach (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER REFERENCES contacts(id),
            application_id INTEGER REFERENCES applications(id),
            channel TEXT DEFAULT 'linkedin_dm'
                CHECK(channel IN ('linkedin_dm','email','linkedin_inmail','referral','cold_intro')),
            subject TEXT,
            body TEXT,
            status TEXT DEFAULT 'draft'
                CHECK(status IN ('draft','sent','replied','no_reply','archived')),
            sent_at TEXT,
            replied_at TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_hash ON jobs(hash);
        CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name);
        CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);
        CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
        CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_contact ON outreach(contact_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_application ON outreach(application_id);
    """)
    conn.commit()

    # Migrate: add columns to companies if they don't exist yet (for existing DBs)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
    migrations = [
        ("domain", "TEXT"),
        ("ats_platform", "TEXT"),
        ("ats_slug", "TEXT"),
        ("ats_api_url", "TEXT"),
        ("resolved_at", "TEXT"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE companies ADD COLUMN {col_name} {col_type}")
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
                   career_url: str = None, domain: str = None,
                   ats_platform: str = None, ats_slug: str = None,
                   ats_api_url: str = None, resolved_at: str = None) -> int:
    conn = get_conn()
    existing = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()

    optional_fields = {
        "lever_slug": lever_slug,
        "greenhouse_slug": greenhouse_slug,
        "career_url": career_url,
        "domain": domain,
        "ats_platform": ats_platform,
        "ats_slug": ats_slug,
        "ats_api_url": ats_api_url,
        "resolved_at": resolved_at,
    }
    updates = {k: v for k, v in optional_fields.items() if v is not None}

    if existing:
        company_id = existing["id"]
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE companies SET {set_clause} WHERE id=?",
                list(updates.values()) + [company_id]
            )
            conn.commit()
    else:
        cols = ["name"] + list(updates.keys())
        placeholders = ",".join(["?"] * len(cols))
        vals = [name] + list(updates.values())
        cur = conn.execute(
            f"INSERT INTO companies ({','.join(cols)}) VALUES ({placeholders})",
            vals
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
    existing = conn.execute("SELECT hash FROM seen_hashes WHERE hash=?", (job_hash,)).fetchone()
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


# --- Contacts ---

def upsert_contact(company_name: str, name: str, title: str = None,
                   linkedin_url: str = None, email: str = None,
                   source: str = "manual", **kwargs) -> int:
    conn = get_conn()
    # Resolve company_id
    comp = conn.execute("SELECT id FROM companies WHERE name=?", (company_name,)).fetchone()
    company_id = comp["id"] if comp else None

    existing = conn.execute(
        "SELECT id FROM contacts WHERE company_name=? AND name=?",
        (company_name, name)
    ).fetchone()

    if existing:
        contact_id = existing["id"]
        updates = {}
        if title:
            updates["title"] = title
        if linkedin_url:
            updates["linkedin_url"] = linkedin_url
        if email:
            updates["email"] = email
        updates.update({k: v for k, v in kwargs.items() if v is not None})
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE contacts SET {set_clause} WHERE id=?",
                list(updates.values()) + [contact_id]
            )
            conn.commit()
    else:
        cur = conn.execute(
            """INSERT INTO contacts (company_id, company_name, name, title,
               linkedin_url, email, source) VALUES (?,?,?,?,?,?,?)""",
            (company_id, company_name, name, title, linkedin_url, email, source)
        )
        contact_id = cur.lastrowid
        conn.commit()
    conn.close()
    return contact_id


def get_contacts(company_name: str = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    if company_name:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE company_name=? ORDER BY created_at DESC LIMIT ?",
            (company_name, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM contacts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Applications ---

def create_application(job_id: int = None, company_name: str = None,
                       title: str = None, url: str = None,
                       referral_contact_id: int = None) -> int:
    conn = get_conn()
    # If job_id given, pull details from jobs table
    if job_id:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job:
            company_name = company_name or job["company_name"]
            title = title or job["title"]
            url = url or job["url"]

    cur = conn.execute(
        """INSERT INTO applications (job_id, company_name, title, url, referral_contact_id)
           VALUES (?,?,?,?,?)""",
        (job_id, company_name, title, url, referral_contact_id)
    )
    app_id = cur.lastrowid
    conn.commit()
    conn.close()
    return app_id


def update_application(app_id: int, **kwargs):
    conn = get_conn()
    kwargs["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(
        f"UPDATE applications SET {set_clause} WHERE id=?",
        list(kwargs.values()) + [app_id]
    )
    conn.commit()
    conn.close()


def get_applications(status: str = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM applications WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Outreach ---

def create_outreach(contact_id: int, application_id: int = None,
                    channel: str = "linkedin_dm", subject: str = None,
                    body: str = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO outreach (contact_id, application_id, channel, subject, body)
           VALUES (?,?,?,?,?)""",
        (contact_id, application_id, channel, subject, body)
    )
    outreach_id = cur.lastrowid
    conn.commit()
    conn.close()
    return outreach_id


def update_outreach(outreach_id: int, **kwargs):
    conn = get_conn()
    set_clause = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(
        f"UPDATE outreach SET {set_clause} WHERE id=?",
        list(kwargs.values()) + [outreach_id]
    )
    conn.commit()
    conn.close()


def get_app_stats() -> dict:
    conn = get_conn()
    stats = {}
    rows = conn.execute(
        "SELECT status, COUNT(*) as n FROM applications GROUP BY status ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        stats[r["status"]] = r["n"]
    stats["total_contacts"] = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    stats["outreach_sent"] = conn.execute(
        "SELECT COUNT(*) FROM outreach WHERE status='sent'"
    ).fetchone()[0]
    stats["outreach_replied"] = conn.execute(
        "SELECT COUNT(*) FROM outreach WHERE status='replied'"
    ).fetchone()[0]
    conn.close()
    return stats
