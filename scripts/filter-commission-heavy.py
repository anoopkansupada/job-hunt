#!/usr/bin/env python3
"""
Filter out commission-heavy sales roles where OTE is misleading.

Rule: Any role that is:
1. Sales-focused (AE, SDR, Account Manager, Sales Manager, Sales Director, etc.)
2. Has "OTE includes base + commission" language in description
3. Is NOT a BD/partnership role (those don't have pure commission)

These get flagged as 'commission_heavy' and downranked from high-match lists.
"""

import sqlite3
import sys
import re

DB_PATH = "/Users/jarvis/.openclaw/workspace/projects/job-hunt/scraper/data/jobs.db"

SALES_TITLES = [
    "Account Executive",
    "Sales Development Representative",
    "SDR",
    "BDR",
    "Enterprise Sales",
    "Sales Manager",
    "Sales Director",
    "Account Manager",
    "Account Management",
    "Territory Manager",
    "Sales Rep",
]

# BD/Partnership roles are OK (not pure commission-driven)
BD_KEYWORDS = [
    "Business Development",
    "Partnerships",
    "Partner Manager",
    "Ecosystem",
    "Strategic Alliance",
    "Channel",
]

def is_commission_heavy(title, description):
    """Check if a role is commission-heavy sales."""
    
    # Check if it's a sales role
    is_sales_role = any(keyword in title for keyword in SALES_TITLES)
    if not is_sales_role:
        return False
    
    # Exclude BD/partnership roles
    is_bd_role = any(keyword in title for keyword in BD_KEYWORDS)
    if is_bd_role:
        return False
    
    # Check if description mentions commission-based compensation
    if not description:
        return False
    
    commission_indicators = [
        r"may or may not be earned depending on performance",
        r"contingent on performance",
        r"variable commission",
        r"high percentage commission",
        r"quota-carrying",
    ]
    
    for pattern in commission_indicators:
        if re.search(pattern, description, re.IGNORECASE):
            return True
    
    return False

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Add commission_heavy column if it doesn't exist
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN commission_heavy INTEGER DEFAULT 0;")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Find and flag commission-heavy roles
    c.execute("SELECT id, title, description FROM jobs WHERE match_score >= 5")
    rows = c.fetchall()
    
    flagged_count = 0
    for job_id, title, description in rows:
        if is_commission_heavy(title, description):
            c.execute("UPDATE jobs SET commission_heavy = 1 WHERE id = ?", (job_id,))
            flagged_count += 1
    
    conn.commit()
    
    # Report
    c.execute("""
        SELECT company, COUNT(*) as count
        FROM jobs 
        WHERE commission_heavy = 1 AND match_score >= 5
        GROUP BY company
        ORDER BY count DESC
    """)
    
    print("\n🚨 COMMISSION-HEAVY ROLES FILTERED (match score 5+):\n")
    print("Company | Count")
    print("--- | ---")
    
    total = 0
    for company, count in c.fetchall():
        print(f"{company} | {count}")
        total += count
    
    print(f"\n**Total flagged:** {flagged_count} roles")
    print(f"**Impact on high-match (7+):** Next rebuild will exclude these from top 10 list\n")
    
    conn.close()

if __name__ == "__main__":
    main()
