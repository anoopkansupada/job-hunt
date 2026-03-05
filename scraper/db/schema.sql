-- Job Hunt Scout Database Schema
-- SHA256(company+title+url) = jobs.id

-- Jobs discovered by scouts
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,              -- SHA256 hash of company+title+url
    source TEXT NOT NULL,             -- 'lever', 'greenhouse', 'linkedin', 'indeed', 'wellfound', 'career_page'
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    location TEXT,
    team TEXT,
    salary_range TEXT,
    description TEXT,
    posted_date TEXT,
    scraped_at TEXT NOT NULL,
    match_score INTEGER DEFAULT 0,    -- 0-12 keyword match score
    match_keywords TEXT,              -- JSON array of matched keywords
    status TEXT DEFAULT 'NEW',        -- NEW, VIEWED, APPLYING, APPLIED, REJECTED, ARCHIVED
    notes TEXT,
    UNIQUE(url)
);

-- Scout run history
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,           -- 'ats', 'boards', 'career_pages', 'full'
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT DEFAULT 'RUNNING',    -- RUNNING, COMPLETE, FAILED
    jobs_found INTEGER DEFAULT 0,
    jobs_new INTEGER DEFAULT 0,
    jobs_alerted INTEGER DEFAULT 0,
    error TEXT
);

-- Alert history
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    alerted_at TEXT NOT NULL,
    channel TEXT DEFAULT 'slack',
    match_score INTEGER,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Target companies config (mirrors sources.yaml)
CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lever_slug TEXT,
    greenhouse_slug TEXT,
    career_page_url TEXT,
    active INTEGER DEFAULT 1,
    last_checked TEXT
);
