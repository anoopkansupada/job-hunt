"""
ATS Platform Detection -- deterministic pattern matching.

Given a URL or HTML body, detect which Applicant Tracking System a company uses
and extract the board slug needed for API access.

Supported platforms:
  - Greenhouse  (boards.greenhouse.io, boards-api.greenhouse.io, job-boards.greenhouse.io)
  - Lever       (jobs.lever.co)
  - Ashby       (jobs.ashbyhq.com)
  - Workday     (*.wd1-5.myworkdayjobs.com)
  - SmartRecruiters (jobs.smartrecruiters.com)
  - BambooHR    (*.bamboohr.com/careers)
  - Recruitee   (*.recruitee.com)
  - Jobvite     (jobs.jobvite.com)
"""
import re
from dataclasses import dataclass


@dataclass
class ATSResult:
    platform: str       # e.g. "greenhouse", "lever"
    slug: str           # board identifier for API calls
    careers_url: str    # the URL we matched against
    api_url: str        # direct API endpoint


# Each pattern: (compiled regex, platform name, slug group index, api_url template)
# Applied against URLs found in page HTML
_URL_PATTERNS = [
    # Greenhouse variants
    (re.compile(r'boards\.greenhouse\.io/([a-zA-Z0-9_-]+)'), 'greenhouse',
     lambda slug: f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'),
    (re.compile(r'boards-api\.greenhouse\.io/v1/boards/([a-zA-Z0-9_-]+)'), 'greenhouse',
     lambda slug: f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'),
    (re.compile(r'job-boards\.greenhouse\.io/([a-zA-Z0-9_-]+)'), 'greenhouse',
     lambda slug: f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'),

    # Lever
    (re.compile(r'jobs\.lever\.co/([a-zA-Z0-9_-]+)'), 'lever',
     lambda slug: f'https://api.lever.co/v0/postings/{slug}?mode=json'),

    # Ashby
    (re.compile(r'jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]+)'), 'ashby',
     lambda slug: f'https://api.ashbyhq.com/posting-api/job-board/{slug}'),

    # SmartRecruiters
    (re.compile(r'jobs\.smartrecruiters\.com/([a-zA-Z0-9_-]+)'), 'smartrecruiters',
     lambda slug: f'https://api.smartrecruiters.com/v1/companies/{slug}/postings'),

    # Workday (wd1 through wd5)
    (re.compile(r'([a-zA-Z0-9_-]+)\.wd[1-5]\.myworkdayjobs\.com'), 'workday',
     lambda slug: None),  # Workday has no clean public API

    # BambooHR
    (re.compile(r'([a-zA-Z0-9_-]+)\.bamboohr\.com/(?:careers|jobs)'), 'bamboohr',
     lambda slug: f'https://api.bamboohr.com/api/gateway.php/{slug}/v1/applicant_tracking/jobs'),

    # Recruitee
    (re.compile(r'([a-zA-Z0-9_-]+)\.recruitee\.com'), 'recruitee',
     lambda slug: f'https://api.recruitee.com/c/{slug}/offers'),

    # Jobvite
    (re.compile(r'jobs\.jobvite\.com/([a-zA-Z0-9_-]+)'), 'jobvite',
     lambda slug: None),  # Jobvite API requires auth
]

# Patterns to find in raw HTML that indicate an embedded ATS
_HTML_PATTERNS = [
    # Greenhouse embed script / iframe
    (re.compile(r'greenhouse\.io/embed/job_board[^"]*\bfor=([a-zA-Z0-9_-]+)'), 'greenhouse',
     lambda slug: f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'),
    (re.compile(r'app\.greenhouse\.io/embed/job_board[^"]*\bfor=([a-zA-Z0-9_-]+)'), 'greenhouse',
     lambda slug: f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'),

    # Lever embed
    (re.compile(r'jobs\.lever\.co/([a-zA-Z0-9_-]+)'), 'lever',
     lambda slug: f'https://api.lever.co/v0/postings/{slug}?mode=json'),

    # Ashby embed
    (re.compile(r'jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]+)'), 'ashby',
     lambda slug: f'https://api.ashbyhq.com/posting-api/job-board/{slug}'),
]


def detect_from_url(url: str) -> ATSResult | None:
    """Detect ATS platform from a single URL string."""
    for pattern, platform, api_fn in _URL_PATTERNS:
        m = pattern.search(url)
        if m:
            slug = m.group(1).lower()
            api_url = api_fn(slug)
            return ATSResult(
                platform=platform,
                slug=slug,
                careers_url=url,
                api_url=api_url or "",
            )
    return None


def detect_from_html(html: str, source_url: str = "") -> ATSResult | None:
    """Scan HTML body for ATS platform signatures.

    Checks all hrefs and src attributes first (most reliable),
    then falls back to HTML body patterns for embedded boards.
    """
    # Extract all URLs from href and src attributes
    urls = re.findall(r'(?:href|src|action)=["\']([^"\']+)["\']', html)

    # Also check for URLs in JavaScript strings (common for SPAs)
    urls += re.findall(r'["\'](https?://[^"\']+)["\']', html)

    # Check each extracted URL against known ATS patterns
    for url in urls:
        result = detect_from_url(url)
        if result:
            result.careers_url = source_url or result.careers_url
            return result

    # Fall back to HTML body pattern matching (embedded boards)
    for pattern, platform, api_fn in _HTML_PATTERNS:
        m = pattern.search(html)
        if m:
            slug = m.group(1).lower()
            api_url = api_fn(slug)
            return ATSResult(
                platform=platform,
                slug=slug,
                careers_url=source_url,
                api_url=api_url or "",
            )

    return None


# Known ATS platforms we can actually scrape via public API
SCRAPEABLE_PLATFORMS = {"greenhouse", "lever", "ashby", "smartrecruiters", "recruitee"}
