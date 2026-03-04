# Job Hunt — Comprehensive Build Plan

_Created: 2026-03-04 | Owner: Anoop | Repo: anoopkansupada/job-hunt_

---

## Vision

Move from **reactive** (paste a JD you found manually) → **proactive** (system finds, filters, and surfaces jobs automatically, then you use the optimizer to nail the application).

```
BEFORE: Anoop finds job → pastes into optimizer → applies
AFTER:  Pipeline finds jobs 6x/day → filters → alerts Anoop → 
        Anoop clicks → job auto-loaded in optimizer → applies
```

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     JOB DISCOVERY PIPELINE                       │
│  (Mac mini, system cron, zero AI, zero token cost)              │
│                                                                  │
│  Sources:                  Scrapers:           Output:           │
│  ┌───────────────┐        ┌──────────────┐    ┌──────────────┐ │
│  │ Lever API     │──────→ │ lever_api.py │──→ │ jobs/        │ │
│  │ Greenhouse    │──────→ │ greenhouse.py│    │ YYYY-MM-DD/  │ │
│  │ LinkedIn      │──────→ │ job_board.py │    │   job_xyz.md │ │
│  │ Indeed        │──────→ │   (Crawl4AI) │    │   job_abc.md │ │
│  │ Wellfound     │──────→ │              │    │   SUMMARY.md │ │
│  │ Built In NYC  │──────→ │ career_page  │    └──────────────┘ │
│  │ Career pages  │──────→ │   .py        │           │         │
│  └───────────────┘        └──────────────┘           │         │
│                                   │                   │         │
│                           filter.py + dedup.py        │         │
│                                   │                   ↓         │
│                               notify.py ──→ Slack #job-hunt     │
└─────────────────────────────────────────────────────────────────┘
                                                         │
                                                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                     RESUME OPTIMIZER (LIVE)                      │
│  Next.js app — localhost:3000 or Tailscale URL                  │
│                                                                  │
│  ← Auto-load job from pipeline output (future integration)      │
│                                                                  │
│  5 Strategies: TAILOR | AUDIT | BULLETS | COVER | KEYWORDS      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Resume Optimizer (Status: ✅ LIVE)

### What Exists
- `/app` — Next.js 14 + React 18 + Tailwind CSS
- Password-protected login page
- 5 strategy tabs, all streaming Claude responses
- Google Docs import + PDF upload + URL scrape
- Deployed to GitHub (`anoopkansupada/job-hunt`), Vercel-ready

### 5 Strategies (All Implemented)

| ID | Name | What Claude Does |
|----|------|-----------------|
| `tailor` | Tailor Resume | Rewrites weakest bullets, fills gaps, optimizes summary |
| `audit` | Resume Audit | Scores each requirement present/missing/weak, ATS check |
| `bullet` | Bullet Generator | Converts raw achievements → quantified, metrics-driven bullets |
| `cover` | Cover Letter | 3-paragraph, <250 words, role-specific, keywords baked in |
| `keywords` | Keywords Map | Coverage map: what you hit vs. missing, ATS %, suggested fixes |

### Pending Optimizer Improvements (Low Priority)
- [ ] "Load from Discovery" button — pre-populate JD field from a scraped job
- [ ] Job history tab — browse previously analyzed jobs
- [ ] Export to PDF/DOCX

---

## Part 2: Job Discovery Pipeline (Status: 🔴 BUILD NEXT)

### File Structure
```
scraper/
├── run.py                  # Main orchestrator — called by cron
├── requirements.txt        # Python deps
├── sources.yaml            # Config: roles, companies, search terms, filters
├── config.example.yaml     # Template (committed, safe to share)
├── seen_jobs.json          # Dedup cache (gitignored)
├── scrapers/
│   ├── __init__.py
│   ├── lever_api.py        # Lever API scraper
│   ├── greenhouse_api.py   # Greenhouse API scraper  
│   ├── job_board.py        # Generic board scraper (Crawl4AI)
│   └── career_page.py      # Direct company career page scraper
├── filter.py               # Role/keyword/location matching
├── dedup.py                # seen_jobs.json read/write
├── notify.py               # Slack webhook alerts
└── jobs/                   # Output (gitignored)
    └── YYYY-MM-DD/
        ├── lever_stripe_spm.md
        ├── greenhouse_figma_partnerships.md
        └── SUMMARY.md
```

---

### Source Tier System

#### Tier 1: ATS APIs (Priority — pure JSON, no scraping, no browser)

**Lever** — Many startups + tech companies
```
GET https://api.lever.co/v0/postings/{company-slug}?mode=json
```
Returns: full JD, teams, location, salary, posted date. Zero auth required.

**Greenhouse** — Enterprise tech + Series B+ startups
```
GET https://boards-api.greenhouse.io/v1/boards/{company-slug}/jobs?content=true
```
Returns: full JD structured JSON. Zero auth required.

Seed these with target companies. Example companies to check:
- Stripe, Figma, Notion, Ramp, Brex, Rippling (Lever/Greenhouse?)
- Whatnot, Coinbase, Kraken, Chainalysis (Web3 angle)
- Any company in `sources.yaml` company list

> 🎯 **Priority:** Build Lever + Greenhouse first. These cover 60%+ of tech companies, run instantly, return clean structured data, and require zero browser/auth overhead.

#### Tier 2: Job Boards (Crawl4AI — JS-rendered)

| Board | URL Pattern | Best For |
|-------|-------------|---------|
| LinkedIn Jobs | `linkedin.com/jobs/search/?keywords={role}&location={loc}` | Broad corporate |
| Indeed | `indeed.com/jobs?q={role}&l={location}` | Volume |
| Wellfound | `wellfound.com/jobs?role={role}` | Startups |
| Built In NYC | `builtinnyc.com/jobs` | NYC-focused |
| Himalayas | `himalayas.app/jobs` | Remote-first |
| Web3.career | `web3.career` | Web3/crypto roles |

**Crawl4AI config:**
```python
# Locally running at port 11234 (already installed on Mac mini)
CRAWL4AI_URL = "http://localhost:11234"
```

#### Tier 3: Direct Career Pages (web_fetch / Crawl4AI)

For high-priority target companies not on Lever/Greenhouse, or for companies where you want the full JD directly.

**Detection logic:**
1. Try `company.com/careers` or `company.com/jobs`
2. If JS-rendered → Crawl4AI
3. If static HTML → web_fetch (faster)

---

### sources.yaml — Master Config

```yaml
# Target roles for Anoop
roles:
  - "Head of Partnerships"
  - "VP Partnerships"
  - "Director of Partnerships"
  - "Head of Ecosystem"
  - "VP Business Development"
  - "Director of Business Development"
  - "Head of Growth"
  - "VP Growth"
  - "Chief of Staff"
  - "Head of Web3 Partnerships"
  - "Partnerships Lead"

# Location preferences
locations:
  - "New York"
  - "NYC"
  - "Remote"
  - "Hybrid"

# Seniority filter (must match at least one)
seniority:
  - "Head"
  - "VP"
  - "Director"
  - "Senior"
  - "Lead"
  - "Principal"

# Keywords that boost match score
boost_keywords:
  - "Web3"
  - "crypto"
  - "blockchain"
  - "DeFi"
  - "ecosystem"
  - "protocol"
  - "startup"
  - "Series B"
  - "Series C"

# Keywords that disqualify a listing
exclude_keywords:
  - "Junior"
  - "Entry Level"
  - "Intern"
  - "Associate"
  - "Coordinator"

# Min keyword match to store (even if not alerted)
min_store_score: 2

# Min keyword match to alert on Slack
min_alert_score: 5

# Target companies (Lever/Greenhouse API + career page)
companies:
  # Web3 / Crypto
  - name: Coinbase
    lever_slug: coinbase
  - name: Kraken
    greenhouse_slug: kraken
  - name: Chainalysis
    greenhouse_slug: chainalysis
  - name: Alchemy
    lever_slug: alchemyplatform
  - name: Consensys
    greenhouse_slug: consensys
  - name: Ripple
    greenhouse_slug: ripple
  - name: Polygon
    career_page: https://polygon.technology/careers
  - name: Arbitrum Foundation
    career_page: https://arbitrum.foundation/jobs
  - name: Uniswap Labs
    greenhouse_slug: uniswaplabs
  
  # Fintech
  - name: Ramp
    greenhouse_slug: ramp
  - name: Brex
    greenhouse_slug: brex
  - name: Stripe
    lever_slug: stripe
  - name: Plaid
    greenhouse_slug: plaid
  - name: Rippling
    lever_slug: rippling
  
  # Tech / Growth
  - name: Notion
    greenhouse_slug: notion
  - name: Figma
    greenhouse_slug: figma
  - name: Whatnot
    greenhouse_slug: whatnot
  - name: Carta
    greenhouse_slug: carta

# Job boards
boards:
  - name: LinkedIn
    url: "https://www.linkedin.com/jobs/search/?keywords={role}&location=New+York"
    method: crawl4ai
    frequency: every_12h
  - name: Indeed
    url: "https://www.indeed.com/jobs?q={role}&l=New+York%2C+NY"
    method: crawl4ai
    frequency: every_12h
  - name: Wellfound
    url: "https://wellfound.com/jobs?role={role_slug}"
    method: crawl4ai
    frequency: every_12h
  - name: Built In NYC
    url: "https://www.builtinnyc.com/jobs/search?search={role}"
    method: web_fetch
    frequency: every_24h
  - name: Web3.career
    url: "https://web3.career/{role_slug}-jobs"
    method: web_fetch
    frequency: every_24h
```

---

### Job Markdown Format (Output)

Each discovered job saved as:
```
scraper/jobs/2026-03-04/lever_stripe_head-of-partnerships.md
```

Contents:
```markdown
---
id: lever_stripe_head-of-partnerships_2026-03-04
source: lever_api
company: Stripe
title: Head of Partnerships
posted: 2026-03-04
url: https://jobs.lever.co/stripe/abc123
location: New York, NY / Remote
team: Business Development
match_score: 9
status: NEW
---

## Head of Partnerships — Stripe

**Source:** Lever API  
**Posted:** 2026-03-04  
**Location:** New York, NY / Remote  
**Team:** Business Development  
**Match Score:** 9/12 ⭐

### Job Description

[full JD text here]

### Match Analysis

**Keywords hit (9):** partnerships, ecosystem, Web3, crypto, growth, BD, 
startup, Series C, NYC  
**Keywords missing (3):** DeFi, protocol, cross-functional  

---
_Scraped: 2026-03-04 08:02 EST | To optimize: load this file into the app_
```

---

### Cron Schedule

All jobs go in the **system crontab** (zero AI, zero tokens):

```cron
# Job Discovery Pipeline
# Lever + Greenhouse APIs (fast, cheap, reliable)
0 */4 * * *   cd /Users/jarvis/.openclaw/workspace/projects/job-hunt/scraper && python run.py --sources lever,greenhouse >> logs/scraper.log 2>&1

# Job boards (heavier, 12h cycle)
0 8,20 * * *  cd /Users/jarvis/.openclaw/workspace/projects/job-hunt/scraper && python run.py --sources boards >> logs/scraper.log 2>&1

# Career pages (direct company pages, 2x daily)
30 8,20 * * * cd /Users/jarvis/.openclaw/workspace/projects/job-hunt/scraper && python run.py --sources careers >> logs/scraper.log 2>&1

# Daily digest to Slack #job-hunt
0 9 * * *     cd /Users/jarvis/.openclaw/workspace/projects/job-hunt/scraper && python notify.py --digest >> logs/notify.log 2>&1
```

---

### Slack Alert Format

**Real-time alert** (on new match_score ≥ 5):
```
🎯 *New Job Match* — Head of Partnerships @ Stripe
Score: 9/12 | Source: Lever | Location: NYC / Remote
https://jobs.lever.co/stripe/abc123

Keywords: partnerships, ecosystem, Web3, crypto, growth
→ Open in optimizer to tailor your resume
```

**Daily 9am digest:**
```
📋 *Job Hunt Daily Digest — March 4*
Found 14 new listings since yesterday

⭐ Top matches:
• Head of Partnerships @ Stripe (9/12) — Lever
• VP BD @ Chainalysis (8/12) — Greenhouse  
• Director of Ecosystem @ Alchemy (7/12) — Lever

📦 All jobs: /scraper/jobs/2026-03-04/SUMMARY.md
```

---

## Part 3: Optimizer + Discovery Integration (Future)

Once the pipeline is live, close the loop:

1. **"Browse Jobs" tab** in the optimizer app — reads `scraper/jobs/YYYY-MM-DD/*.md` files via API route
2. **One-click load** — clicking a job pre-fills the JD field in the optimizer
3. **Status tracking** — mark jobs as Applied/Interviewing/Rejected from the UI, stored in `seen_jobs.json`

---

## Build Sequence

### Sprint 1 — Scraper Core (Build First)
- [ ] `scraper/requirements.txt`
- [ ] `scraper/sources.yaml` (with Anoop's target roles + companies filled in)
- [ ] `scraper/dedup.py`
- [ ] `scraper/filter.py`
- [ ] `scraper/scrapers/lever_api.py` ← start here, cleanest win
- [ ] `scraper/scrapers/greenhouse_api.py`
- [ ] `scraper/run.py` (orchestrator, Lever + Greenhouse only)
- [ ] Test run: `python run.py --dry-run`

### Sprint 2 — Boards + Notifications
- [ ] `scraper/scrapers/job_board.py` (LinkedIn, Indeed, Wellfound via Crawl4AI)
- [ ] `scraper/scrapers/career_page.py` (company career pages)
- [ ] `scraper/notify.py` (Slack webhook)
- [ ] Add cron entries to Mac mini system crontab

### Sprint 3 — Close the Loop
- [ ] "Browse Jobs" tab in Next.js optimizer
- [ ] One-click JD loader
- [ ] Application status tracking
- [ ] Weekly email/Slack summary with stats

---

## Key Technical Notes

### Crawl4AI (Already Running Locally)
```
Port: 11234 (or 11235)
No API key, no rate limits, handles JS rendering
Use for: LinkedIn, Indeed, Wellfound, any JS-heavy career page
```

### Lever API (No Auth Required)
```python
import requests

def get_lever_jobs(company_slug: str) -> list:
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    r = requests.get(url, timeout=10)
    return r.json() if r.status_code == 200 else []
```

### Greenhouse API (No Auth Required)
```python
def get_greenhouse_jobs(company_slug: str) -> list:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    r = requests.get(url, timeout=10)
    data = r.json()
    return data.get("jobs", []) if r.status_code == 200 else []
```

### Dedup Strategy
- Hash = `{company}_{title}_{url}` → SHA256 → store in `seen_jobs.json`
- On each run: check hash before writing/alerting
- Seen jobs: re-check after 30 days (JDs expire and re-post)

---

## What's Needed From Anoop Before Building

1. **Target roles confirmed** — review the `sources.yaml` roles list above, add/remove
2. **Target company list** — any additions beyond the seed list above?
3. **Slack webhook URL** — for `#job-hunt` alerts (or confirm I should pull from env)
4. **Seniority bar** — is "Senior" level OK or Director+ only?

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Jobs discovered per day | 20–50 (filtered), 200–500 (raw) |
| False positive rate | <20% (strong filter calibration) |
| New match alert lag | <4h from posting |
| Scraper uptime | >95% (system cron, simple Python) |
| Token cost | $0 (no AI in pipeline) |
| Time to apply (with optimizer) | <30min from discovery to tailored app |
