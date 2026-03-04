# Job Hunt — Career Intelligence Platform

Anoop's personal job search system. Two components working together.

## Components

### `/app` — Resume Optimizer (Live)
Next.js 14 app. Paste a job description → get a tailored resume, cover letter, gap analysis, keyword map. 5 strategies, all streaming Claude in real time.

```bash
cd app && npm run dev   # → http://localhost:3000
```

### `/scraper` — Job Discovery Pipeline (Building)
Python cron pipeline. Pulls from Lever API, Greenhouse API, job boards, and company career pages. Filters for match. Saves as markdown. Alerts on Slack.

```bash
cd scraper && python run.py --dry-run
```

---

## Architecture

```
job-hunt/
├── app/                → Next.js optimizer (Vercel-deployed)
│   ├── app/api/        → 5 strategy API routes (Claude streaming)
│   ├── components/     → UI
│   └── README.md
├── scraper/            → Job discovery engine (Mac mini cron)
│   ├── scrapers/       → lever_api.py, greenhouse_api.py, job_board.py
│   ├── sources.yaml    → Target roles, companies, filters
│   └── README.md
├── PLAN.md             ← Full architecture + build roadmap
└── README.md           ← This file
```

## Docs

- **[PLAN.md](PLAN.md)** — Full architecture, build sequence, scraper design
- **[app/README.md](app/README.md)** — Optimizer setup and features
- **[scraper/README.md](scraper/README.md)** — Pipeline setup and config

## Status

| Component | Status |
|-----------|--------|
| Resume Optimizer | ✅ Live |
| Lever/Greenhouse API scraper | 🔴 Building |
| Job board scraper | 🔴 Building |
| Career page scraper | 🔴 Building |
| Slack alerts | 🔴 Building |
| Optimizer ↔ Pipeline integration | ⏳ Planned |
