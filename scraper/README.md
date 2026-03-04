# Job Discovery Pipeline

Automated job scraping engine. Finds jobs, filters for match, alerts via Slack.

## Quick Start

```bash
cd scraper/
pip install -r requirements.txt
cp config.example.yaml config.yaml   # edit with your targets
python run.py --dry-run              # test (no writes)
python run.py --sources lever,greenhouse  # run Tier 1 sources
python run.py --all                  # run everything
```

## Sources

| Tier | Sources | Method | Frequency |
|------|---------|--------|-----------|
| 1 | Lever API, Greenhouse API | Direct JSON (no scraping) | Every 4h |
| 2 | LinkedIn, Indeed, Wellfound, Built In NYC | Crawl4AI | Every 12h |
| 3 | Company career pages | Crawl4AI / web_fetch | 8am + 8pm |

## Output

Jobs saved as markdown: `jobs/YYYY-MM-DD/{source}_{company}_{title}.md`  
Daily digest: `jobs/YYYY-MM-DD/SUMMARY.md`  
Alerts: Slack `#job-hunt` (match_score ≥ 5)

## Config

Edit `config.yaml`:
- `roles` — target job titles
- `companies` — target companies (with ATS slugs)
- `filters` — seniority, location, keyword thresholds
- `slack_webhook` — alert destination

See `../PLAN.md` for full architecture.
