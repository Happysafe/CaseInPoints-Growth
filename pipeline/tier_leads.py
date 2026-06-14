"""
Assigns outreach tiers to leads based on the REF 2021 impact sub-profile.

The impact GPA mean is computed from the cached REF results data
(`ref_results_scraper`), not a hand-maintained table:
- UoA-known leads use their (university × UoA) impact sub-profile.
- Leads with no inferred UoA (REF-office / cross-institutional contacts) fall
  back to the institution's university-wide impact mean.
- "?" only when the institution can't be matched in the results data at all.

Tier 1 (mean ≤ 3.10) — lowest-scoring, test cohort, send first
Tier 2 (mean 3.11–3.55) — mid-range, send after Tier 1 learning
Tier 3 (mean ≥ 3.56) — high-value, send last with most refined prompts
"""
from __future__ import annotations

import logging

from pipeline.ref_results_scraper import get_profile, get_university_profile, quality_mean

logger = logging.getLogger(__name__)


def _assign_tier(mean: float) -> str:
    if mean <= 3.10:
        return "1"
    if mean <= 3.55:
        return "2"
    return "3"


def get_tier_for_lead(lead: dict) -> tuple[str, float | None]:
    """
    Returns (tier, mean_score) for a lead.

    Prefers the lead's (university × UoA) impact sub-profile; falls back to the
    institution's university-wide impact mean when the lead has no UoA or that
    UoA submission isn't in the results data. tier is "?" / mean None only when
    the institution can't be matched at all.
    """
    university = lead.get("university", "")
    uoa_code = lead.get("uoa_code")

    impact = None
    if uoa_code:
        profile = get_profile(university, uoa_code, 2021)
        if profile:
            impact = profile.get("impact")

    if not impact:
        uni_profile = get_university_profile(university, 2021)
        if uni_profile:
            impact = uni_profile.get("impact")

    if not impact:
        return "?", None

    mean = quality_mean(impact)
    return _assign_tier(mean), round(mean, 2)


def tier_leads(leads: list[dict]) -> list[dict]:
    """
    Adds `outreach_tier` and `uoa_mean_score` fields to each lead in-place.
    Returns the same list (does not write to disk — caller saves).
    """
    missing: list[str] = []

    for lead in leads:
        tier, mean = get_tier_for_lead(lead)
        lead["outreach_tier"] = tier
        lead["uoa_mean_score"] = mean
        if tier == "?":
            missing.append(
                f"  {lead.get('contact_name', '?')} — {lead.get('university', '?')} "
                f"(UoA {lead.get('uoa_code', '?')})"
            )

    if missing:
        logger.warning(
            "No REF impact data for %d lead(s) — these will be skipped (tier='?'):\n%s",
            len(missing),
            "\n".join(missing),
        )

    counts = {"1": 0, "2": 0, "3": 0, "?": 0}
    for lead in leads:
        tier = lead.get("outreach_tier", "?")
        counts[tier] = counts.get(tier, 0) + 1

    logger.info(
        "Tier assignment complete — Tier 1: %d | Tier 2: %d | Tier 3: %d | Unknown: %d",
        counts["1"], counts["2"], counts["3"], counts["?"],
    )

    return leads
