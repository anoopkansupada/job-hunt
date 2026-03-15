#!/usr/bin/env python3
"""
Daily job matching script for Anoop's job hunt.
Fetches new jobs, ranks them, alerts on high matches.

Runs via cron: 8:00 AM EST, Mon-Fri
Cost: ~$0.10/day (Claude Haiku ranking)
"""

import subprocess
import sys
import json
import os
from pathlib import Path
from datetime import datetime

# Add scraper to path
SCRAPER_DIR = Path(__file__).parent.parent / "scraper"
sys.path.insert(0, str(SCRAPER_DIR))

def main():
    print(f"[{datetime.now().isoformat()}] Starting daily job match...")
    
    # Run ranking agent on new jobs (limit 50 per day)
    try:
        from agents.ranking_agent import main as rank_jobs
        rank_jobs(limit=50)
        print("✅ Ranking complete")
    except Exception as e:
        print(f"❌ Ranking failed: {e}")
        sys.exit(1)
    
    # Query for new 8+ matches
    import sqlite3
    db = SCRAPER_DIR / "data" / "jobs.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    
    new_high = conn.execute(
        "SELECT title, company, location, match_score, url FROM jobs "
        "WHERE match_score >= 8 AND notified = 0 AND commission_heavy = 0 "
        "ORDER BY match_score DESC LIMIT 20"
    ).fetchall()
    
    if new_high:
        # Build Slack message
        msg = f"🎯 *{len(new_high)} New High-Match Jobs* (8+/10)\n_Daily ranking complete_\n\n"
        
        for job in new_high:
            msg += f"*{job['title']}* @ {job['company']}\n{job['location']} • Score: {job['match_score']}/13\n<{job['url']}|Apply>\n\n"
        
        # Send to Slack via webhook
        webhook = os.getenv("SLACK_WEBHOOK_URL")
        if webhook:
            subprocess.run([
                "curl", "-X", "POST",
                "-H", "Content-type: application/json",
                "--data", json.dumps({"text": msg}),
                webhook
            ])
        
        # Mark as notified
        for job in new_high:
            conn.execute("UPDATE jobs SET notified = 1 WHERE id = ?", (job['id'],))
        conn.commit()
    
    conn.close()
    print(f"✅ {len(new_high)} high-match jobs notified to #job-hunt")

if __name__ == "__main__":
    main()
