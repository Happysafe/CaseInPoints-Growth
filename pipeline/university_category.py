"""
Classifies universities into REF trajectory categories from their university-wide
Overall sub-profile, comparing REF 2014 and REF 2021.

The Overall (not Impact) sub-profile is used because REF 2021 impact scores are
inflated sector-wide — almost every research-intensive university clears 50% 4* on
impact, so it can't discriminate. Overall 4* spreads ~21–67% and yields a genuine
four-way split. (The CRM's separate "Impact 4*" columns are unaffected.)

Categories (first match wins — strength dominates, then risk, then momentum):
    Leaders   — 2021 Overall 4* >= 50%               → maintain & protect for REF 2029
    At Risk   — 2021 4* < 35% AND 2*+1*+uncl > 20%   → prioritise impact development
    Improvers — 4* rose by >= +10pp since 2014        → scale best practices
    Stagnant  — everything else                       → diagnose the plateau

This is orthogonal to `tier_leads` (per-UoA, single-year, governs *when* to contact):
category is per-university, two-year, and governs *how* to pitch.
"""
from __future__ import annotations

import logging

from pipeline.ref_results_scraper import get_university_profile

logger = logging.getLogger(__name__)

# Sub-profile the classification is computed on (see module docstring).
PROFILE = 'overall'

# Thresholds (percentage points, 0–100 scale) — tune after reviewing a first run.
LEADERS_4STAR = 50.0          # 2021 4* at or above this → Leaders
AT_RISK_4STAR = 35.0          # 2021 4* below this ...
AT_RISK_TAIL = 20.0           # ... and 2021 (2*+1*+unclassified) above this → At Risk
IMPROVERS_DELTA_4STAR = 10.0  # 4* gain (2021−2014) at or above this → Improvers

# Memoise per normalised university name — the lead set covers ~22 institutions,
# so this avoids recomputing the profile lookup once per lead.
_cache: dict[str, tuple[str | None, dict]] = {}


def _clear_cache() -> None:
    """Reset the memoisation cache (used by tests)."""
    _cache.clear()


def _classify(f21: float, low21: float, delta_4star: float | None) -> str:
    if f21 >= LEADERS_4STAR:
        return "Leaders"
    if f21 < AT_RISK_4STAR and low21 > AT_RISK_TAIL:
        return "At Risk"
    if delta_4star is not None and delta_4star >= IMPROVERS_DELTA_4STAR:
        return "Improvers"
    return "Stagnant"


def classify_university(university: str) -> tuple[str | None, dict]:
    """
    Return (category, metrics) for a university, or (None, {}) when its 2021
    Impact profile can't be matched.

    metrics = {
        "f21": 2021 4* (0–100),
        "f14": 2014 4* (0–100) or None,
        "delta_4star": (2021−2014) 4* in pp, or None when 2014 is missing,
        "delta_3star_plus": (2021−2014) (4*+3*) in pp, or None,
    }
    """
    key = (university or "").strip().lower()
    if key in _cache:
        return _cache[key]

    dist_2021 = (get_university_profile(university, 2021, PROFILE) or {}).get(PROFILE)
    if not dist_2021:
        result = (None, {})
        _cache[key] = result
        return result

    dist_2014 = (get_university_profile(university, 2014, PROFILE) or {}).get(PROFILE)

    f21 = dist_2021.get("4star", 0.0)
    low21 = (
        dist_2021.get("2star", 0.0)
        + dist_2021.get("1star", 0.0)
        + dist_2021.get("unclassified", 0.0)
    )

    if dist_2014:
        f14 = dist_2014.get("4star", 0.0)
        delta_4star = round(f21 - f14, 1)
        delta_3star_plus = round(
            (f21 + dist_2021.get("3star", 0.0)) - (f14 + dist_2014.get("3star", 0.0)), 1
        )
    else:
        f14 = None
        delta_4star = None
        delta_3star_plus = None

    category = _classify(f21, low21, delta_4star)
    metrics = {
        "f21": round(f21, 1),
        "f14": round(f14, 1) if f14 is not None else None,
        "delta_4star": delta_4star,
        "delta_3star_plus": delta_3star_plus,
    }
    result = (category, metrics)
    _cache[key] = result
    return result


def categorise_leads(leads: list[dict]) -> list[dict]:
    """
    Add `university_category`, `change_in_4star`, `change_in_3star_plus` to each
    lead in-place (deltas in pp, or None). Returns the same list; caller saves.
    """
    counts: dict[str, int] = {}
    unmatched: list[str] = []

    for lead in leads:
        category, metrics = classify_university(lead.get("university", ""))
        lead["university_category"] = category
        lead["change_in_4star"] = metrics.get("delta_4star")
        lead["change_in_3star_plus"] = metrics.get("delta_3star_plus")

        label = category or "Unmatched"
        counts[label] = counts.get(label, 0) + 1
        if category is None:
            unmatched.append(lead.get("university", "?"))

    summary = " | ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    logger.info("University category assignment complete — %s", summary)
    if unmatched:
        logger.warning(
            "No REF 2021 Impact profile for %d lead(s): %s",
            len(unmatched), ", ".join(sorted(set(unmatched))),
        )

    return leads
