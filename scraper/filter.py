"""
Job filter/scorer -- deterministic keyword + role + location matching.
No AI, no tokens. Pure string matching against config.yaml.
"""
import re
import yaml
from pathlib import Path


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        config_path = Path(__file__).parent / "config.example.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def score_job(job: dict, config: dict = None) -> tuple[int, int]:
    """
    Score a job against config criteria.
    Returns (match_score, boost_score).

    match_score: 0-12 based on role title, seniority, location match
    boost_score: 0+ based on boost_keywords in description
    """
    if config is None:
        config = load_config()

    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    description = (job.get("description") or "").lower()
    full_text = f"{title} {location} {description}"

    score = 0

    # --- Exclude check (instant disqualify) ---
    for kw in config.get("exclude_keywords", []):
        if kw.lower() in title:
            return 0, 0

    # --- Role match (0-5 points) ---
    roles = config.get("roles", [])
    best_role_score = 0
    for role in roles:
        role_lower = role.lower()
        if role_lower in title:
            best_role_score = 5  # exact match
            break
        # Partial: check individual words (e.g. "partnerships" in "Strategic Partnerships Manager")
        role_words = [w for w in role_lower.split() if len(w) > 3]
        hits = sum(1 for w in role_words if w in title)
        if role_words:
            partial = int(3 * hits / len(role_words))
            best_role_score = max(best_role_score, partial)
    score += best_role_score

    # --- Seniority match (0-3 points) ---
    seniority = config.get("seniority", [])
    for level in seniority:
        if level.lower() in title:
            score += 3
            break

    # --- Location match (0-2 points) ---
    locations = config.get("locations", [])
    for loc in locations:
        if loc.lower() in location:
            score += 2
            break

    # --- Team/department relevance (0-2 points) ---
    team = (job.get("team") or "").lower()
    relevant_teams = ["partnership", "business dev", "growth", "ecosystem",
                      "strategic", "revenue", "sales", "expansion"]
    for t in relevant_teams:
        if t in team or t in title:
            score += 2
            break

    # --- Boost keywords (separate score) ---
    boost = 0
    for kw in config.get("boost_keywords", []):
        if kw.lower() in full_text:
            boost += 1

    return min(score, 12), boost


def passes_threshold(match_score: int, config: dict = None) -> tuple[bool, bool]:
    """Returns (should_store, should_alert) based on config thresholds."""
    if config is None:
        config = load_config()
    min_store = config.get("min_store_score", 2)
    min_alert = config.get("min_alert_score", 5)
    return match_score >= min_store, match_score >= min_alert
