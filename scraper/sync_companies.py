#!/usr/bin/env python3
"""
sync_companies.py — Sync companies.yaml from all data sources.

Sources:
  1. DataHive pipeline DB (buyer_score >= 5, non-disqualified)
  2. Second Brain vault/Companies/ (domain → career_page)

Adds NEW companies only — never removes existing ones.
Preserves ATS slugs already in companies.yaml.

Usage:
    python3 sync_companies.py              # dry-run (shows what would be added)
    python3 sync_companies.py --apply      # write changes to companies.yaml
    python3 sync_companies.py --apply --min-score 6  # only DataHive score >= 6
"""

import argparse
import os
import re
import sys
from pathlib import Path

import sqlite3
import yaml

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRAPER_DIR      = Path(__file__).parent
COMPANIES_YAML   = SCRAPER_DIR / "companies.yaml"
DATAHIVE_DB      = Path.home() / ".openclaw/workspace/projects/datahive/pipeline/datahive.db"
SECOND_BRAIN_DIR = Path.home() / ".openclaw/workspace/second-brain/vault/Companies"

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(name: str) -> str:
    """Lowercase + strip for dedup comparison."""
    return name.lower().strip()


def load_existing(yaml_path: Path) -> tuple[dict, set]:
    """Load companies.yaml, return (data_dict, set_of_normalized_names)."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    existing = set()
    for priority in ["high_priority", "medium_priority", "low_priority"]:
        for c in data["companies"].get(priority, []):
            if isinstance(c, dict):
                existing.add(normalize(c.get("name", "")))
            elif isinstance(c, str):
                existing.add(normalize(c))
    return data, existing


def career_url(domain: str) -> str:
    if not domain:
        return ""
    domain = domain.strip().lstrip("https://").lstrip("http://")
    return f"https://{domain}"


# ── Source 1: DataHive DB ─────────────────────────────────────────────────────

def pull_datahive(existing: set, min_score: int = 5) -> list[dict]:
    """Return new companies from DataHive not already in companies.yaml."""
    if not DATAHIVE_DB.exists():
        print(f"[datahive] DB not found at {DATAHIVE_DB} — skipping")
        return []

    conn = sqlite3.connect(str(DATAHIVE_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT name, buyer_score, website_url, buyer_type, category, description
        FROM companies
        WHERE buyer_score >= ?
          AND status != 'disqualified'
        ORDER BY buyer_score DESC
    """, (min_score,)).fetchall()
    conn.close()

    new = []
    for r in rows:
        name = (r["name"] or "").strip()
        if not name or normalize(name) in existing:
            continue

        score = r["buyer_score"] or 0
        entry = {
            "name": name,
            "source": "datahive",
            "datahive_score": score,
        }
        if r["website_url"]:
            entry["career_page"] = r["website_url"]
        if r["category"]:
            entry["industry"] = r["category"]
        if r["buyer_type"]:
            entry["buyer_type"] = r["buyer_type"]

        new.append(entry)

    return new


# ── Source 2: Second Brain Vault ──────────────────────────────────────────────

def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from a markdown file."""
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}


def pull_second_brain(existing: set) -> list[dict]:
    """Return new companies from Second Brain vault not in companies.yaml."""
    if not SECOND_BRAIN_DIR.exists():
        print(f"[second-brain] Vault not found at {SECOND_BRAIN_DIR} — skipping")
        return []

    new = []
    for fpath in SECOND_BRAIN_DIR.glob("*.md"):
        with open(fpath, encoding="utf-8", errors="ignore") as f:
            content = f.read()

        fm = parse_frontmatter(content)
        name = fm.get("name") or fpath.stem.replace("_", " ").strip()
        if not name or normalize(name) in existing:
            continue

        domain = fm.get("domain", "")
        entry = {
            "name": name,
            "source": "second_brain",
        }
        if domain:
            entry["career_page"] = career_url(domain)
        if fm.get("location"):
            entry["location"] = fm["location"]

        new.append(entry)

    return new


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync companies.yaml from all data sources")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument("--min-score", type=int, default=5, help="Min DataHive buyer_score (default: 5)")
    parser.add_argument("--skip-second-brain", action="store_true", help="Skip Second Brain source")
    args = parser.parse_args()

    print(f"{'DRY RUN — ' if not args.apply else ''}Syncing companies.yaml\n")

    data, existing = load_existing(COMPANIES_YAML)
    print(f"Existing companies: {len(existing)}")

    # ── Pull from each source ─────────────────────────────────────────────────
    dh_new  = pull_datahive(existing, min_score=args.min_score)
    sb_new  = [] if args.skip_second_brain else pull_second_brain(existing | {normalize(c["name"]) for c in dh_new})

    print(f"\nNew from DataHive  (score≥{args.min_score}): {len(dh_new)}")
    for c in dh_new:
        print(f"  [{c['datahive_score']}] {c['name']} — {c.get('career_page','')[:50]}")

    print(f"\nNew from Second Brain: {len(sb_new)}")
    for c in sb_new[:20]:
        print(f"  {c['name']} — {c.get('career_page','')[:50]}")
    if len(sb_new) > 20:
        print(f"  ... and {len(sb_new)-20} more")

    total_new = len(dh_new) + len(sb_new)
    print(f"\nTotal new companies: {total_new}")

    if not args.apply:
        print("\n(dry-run) Pass --apply to write changes.")
        return

    if total_new == 0:
        print("Nothing to add.")
        return

    # ── Merge into medium_priority (score 5-6) or high_priority (score 7+) ───
    for c in dh_new:
        score = c.get("datahive_score", 0)
        if score >= 7:
            data["companies"]["high_priority"].append(c)
        else:
            data["companies"]["medium_priority"].append(c)

    # Second Brain companies go into medium_priority
    for c in sb_new:
        data["companies"]["medium_priority"].append(c)

    # Update stats header
    data["stats"]["total"] = (
        len(data["companies"].get("high_priority", [])) +
        len(data["companies"].get("medium_priority", [])) +
        len(data["companies"].get("low_priority", []))
    )
    data["total"] = data["stats"]["total"]

    from datetime import datetime
    data["generated_at"] = datetime.utcnow().isoformat()
    data["stats"]["last_synced"] = datetime.utcnow().isoformat()

    with open(COMPANIES_YAML, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"\n✅ Written to {COMPANIES_YAML}")
    print(f"   Total companies now: {data['stats']['total']}")


if __name__ == "__main__":
    main()
