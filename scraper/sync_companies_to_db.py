#!/usr/bin/env python3
"""
Sync companies from config.yaml into the SQLite companies table.
Upserts all 109 target companies (lever_slug / greenhouse_slug).

Usage:
    python3 sync_companies_to_db.py
"""

import hashlib
import sqlite3
import yaml
from pathlib import Path

SCRAPER_DIR = Path(__file__).parent
DB_PATH     = SCRAPER_DIR / "data" / "jobs.db"
CONFIG_PATH = SCRAPER_DIR / "config.yaml"


def company_id(name: str) -> str:
    """Stable 12-char ID from company name."""
    return hashlib.sha256(name.lower().strip().encode()).hexdigest()[:12]


def main() -> None:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    companies: list[dict] = cfg.get("companies", [])
    if not companies:
        print("No companies found in config.yaml")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Ensure table exists (in case DB was freshly created)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            lever_slug      TEXT,
            greenhouse_slug TEXT,
            career_page_url TEXT,
            active          INTEGER DEFAULT 1,
            last_checked    TEXT
        )
    """)

    inserted = updated = 0
    for co in companies:
        name = co.get("name", "").strip()
        if not name:
            continue

        cid            = company_id(name)
        lever_slug     = co.get("lever_slug") or None
        greenhouse_slug = co.get("greenhouse_slug") or None
        career_page_url = co.get("career_page_url") or None

        # Check if exists
        row = conn.execute("SELECT id FROM companies WHERE id = ?", (cid,)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE companies
                SET name = ?, lever_slug = ?, greenhouse_slug = ?, career_page_url = ?, active = 1
                WHERE id = ?
                """,
                (name, lever_slug, greenhouse_slug, career_page_url, cid),
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO companies (id, name, lever_slug, greenhouse_slug, career_page_url, active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (cid, name, lever_slug, greenhouse_slug, career_page_url),
            )
            inserted += 1

    conn.commit()
    total = conn.execute("SELECT count(*) FROM companies").fetchone()[0]
    conn.close()

    print(f"✅ Companies synced — inserted: {inserted}, updated: {updated}")
    print(f"   Total rows in companies table: {total}")


if __name__ == "__main__":
    main()
