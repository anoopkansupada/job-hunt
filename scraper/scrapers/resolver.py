"""
Company ATS Resolver -- finds career pages and detects ATS platform.

Given a company name + domain, this module:
  1. Tries common career page URLs directly ({domain}/careers, /jobs, etc.)
  2. Fetches the page HTML
  3. Runs ATS fingerprinting to detect Greenhouse/Lever/Ashby/etc.
  4. Returns the platform + slug for API scraping

No AI involved -- pure HTTP + regex pattern matching.
"""
import time
import requests
from dataclasses import dataclass, field
from scrapers.ats_detect import detect_from_html, detect_from_url, ATSResult


# Common career page paths to try, in order of likelihood
CAREER_PATHS = [
    "/careers",
    "/jobs",
    "/careers/",
    "/jobs/",
    "/about/careers",
    "/company/careers",
    "/join",
    "/join-us",
    "/open-positions",
    "/work-with-us",
    "/team",
]

# Some companies host careers on a subdomain
CAREER_SUBDOMAINS = [
    "careers.{domain}",
    "jobs.{domain}",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class ResolveResult:
    company_name: str
    domain: str
    ats: ATSResult | None = None
    careers_url: str = ""
    error: str = ""
    tried_urls: list[str] = field(default_factory=list)


def _fetch_page(url: str, timeout: int = 12) -> tuple[str, str, int]:
    """Fetch a page, return (html, final_url, status_code).

    Follows redirects. Returns ("", url, 0) on error.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        final_url = r.url
        return r.text, final_url, r.status_code
    except requests.RequestException:
        return "", url, 0


def _normalize_domain(domain: str) -> str:
    """Strip protocol and trailing slash."""
    domain = domain.strip()
    if domain.startswith("http://"):
        domain = domain[7:]
    if domain.startswith("https://"):
        domain = domain[8:]
    domain = domain.rstrip("/")
    return domain


def resolve_company(name: str, domain: str, delay: float = 0.5) -> ResolveResult:
    """Resolve a single company's ATS platform.

    Tries career page URLs, fetches HTML, and fingerprints the ATS.
    """
    domain = _normalize_domain(domain)
    result = ResolveResult(company_name=name, domain=domain)

    # Step 1: Check if the domain itself redirects to an ATS
    # (some companies point careers.company.com -> greenhouse directly)
    base_url = f"https://{domain}"

    # Build candidate URLs
    candidates = []

    # Career subdomains first (often direct ATS redirects)
    for pattern in CAREER_SUBDOMAINS:
        candidates.append(f"https://{pattern.format(domain=domain)}")

    # Main domain + career paths
    for path in CAREER_PATHS:
        candidates.append(f"{base_url}{path}")

    for url in candidates:
        result.tried_urls.append(url)
        html, final_url, status = _fetch_page(url)

        if status == 0 or status >= 400:
            continue

        # Check if we got redirected to a known ATS
        ats = detect_from_url(final_url)
        if ats:
            result.ats = ats
            result.careers_url = final_url
            return result

        # Scan the page HTML for ATS patterns
        ats = detect_from_html(html, source_url=final_url)
        if ats:
            result.ats = ats
            result.careers_url = final_url
            return result

        # If we got a 200 but no ATS detected, save the careers URL
        # (might be a custom careers page with no standard ATS)
        if status == 200 and not result.careers_url:
            result.careers_url = final_url

        if delay:
            time.sleep(delay)

    # Fallback: probe ATS APIs directly with slug guesses
    # This catches SPA-rendered career pages where ATS URLs aren't in raw HTML
    if not result.ats:
        ats = _probe_ats_apis(name, domain)
        if ats:
            result.ats = ats
            if not result.careers_url:
                result.careers_url = ats.careers_url
            return result

    if not result.careers_url and not result.ats:
        result.error = "no_careers_page"
    elif result.careers_url and not result.ats:
        result.error = "no_ats_detected"

    return result


def resolve_batch(companies: list[dict], delay: float = 0.5,
                  on_progress=None) -> list[ResolveResult]:
    """Resolve ATS for a batch of companies.

    Each company dict needs 'name' and 'domain' keys.
    Optional on_progress callback: fn(index, total, result)
    """
    results = []
    total = len(companies)

    for i, comp in enumerate(companies):
        name = comp["name"]
        domain = comp.get("domain", "")

        if not domain:
            r = ResolveResult(company_name=name, domain="", error="no_domain")
            results.append(r)
            if on_progress:
                on_progress(i, total, r)
            continue

        r = resolve_company(name, domain, delay=delay)
        results.append(r)

        if on_progress:
            on_progress(i, total, r)

    return results


def _slugify(name: str) -> list[str]:
    """Generate candidate slugs from a company name.

    'Scale AI' -> ['scaleai', 'scale-ai', 'scale_ai', 'scale']
    'Uniswap Labs' -> ['uniswaplabs', 'uniswap-labs', 'uniswap_labs', 'uniswap']
    """
    import re as _re
    clean = _re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().lower()
    words = clean.split()
    slugs = []
    # joined: "scaleai"
    slugs.append("".join(words))
    # hyphenated: "scale-ai"
    if len(words) > 1:
        slugs.append("-".join(words))
        slugs.append("_".join(words))
        # first word only: "scale"
        slugs.append(words[0])
    return slugs


def _probe_ats_apis(name: str, domain: str) -> ATSResult | None:
    """Try common ATS API endpoints directly using slug guesses.

    This catches SPA-rendered career pages where the ATS URLs
    aren't in the raw HTML.
    """
    slugs = _slugify(name)
    # Also try domain-based slug: "brex.com" -> "brex"
    domain_slug = domain.split(".")[0].lower()
    if domain_slug not in slugs:
        slugs.append(domain_slug)

    # Try Greenhouse first (most common), then Ashby, then Lever
    for slug in slugs:
        # Greenhouse
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and len(data.get("jobs", [])) > 0:
                    return ATSResult(
                        platform="greenhouse",
                        slug=slug,
                        careers_url=f"https://boards.greenhouse.io/{slug}",
                        api_url=f"{url}?content=true",
                    )
        except requests.RequestException:
            pass

        # Ashby
        try:
            url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and len(data.get("jobs", [])) > 0:
                    return ATSResult(
                        platform="ashby",
                        slug=slug,
                        careers_url=f"https://jobs.ashbyhq.com/{slug}",
                        api_url=url,
                    )
        except requests.RequestException:
            pass

        # Lever (often slow/unreliable, try last)
        try:
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    return ATSResult(
                        platform="lever",
                        slug=slug,
                        careers_url=f"https://jobs.lever.co/{slug}",
                        api_url=url,
                    )
        except requests.RequestException:
            pass

    return None


def verify_ats_api(ats: ATSResult) -> bool:
    """Quick check that the detected API endpoint actually returns data."""
    if not ats.api_url:
        return False
    try:
        r = requests.get(ats.api_url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # Greenhouse returns {"jobs": [...]}
            if isinstance(data, dict) and "jobs" in data:
                return len(data["jobs"]) > 0
            # Lever returns [...]
            if isinstance(data, list):
                return len(data) > 0
            # Ashby returns {"jobs": [...]}
            if isinstance(data, dict) and "jobs" in data:
                return len(data["jobs"]) > 0
        return False
    except Exception:
        return False
