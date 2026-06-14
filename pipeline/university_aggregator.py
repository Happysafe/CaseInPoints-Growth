"""
University × UoA aggregator — produces a single overall strength and weakness
across all impact case studies an institution submitted to a Unit of Assessment.

Reads case studies from `data/ref2021_impact_all.xlsx` (via ref_scraper.fetch_case_studies)
and the official quality profile from `data/ref2021_results_all.xlsx`
(via ref_results_scraper.get_profile).

Writes to `output/university_assessments.json`. Idempotent: re-running skips
pairs already present in the cache unless `force=True`.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import anthropic

from pipeline.ref_results_scraper import get_profile
from pipeline.ref_scraper import fetch_case_studies

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / 'output' / 'university_assessments.json'

SYSTEM_PROMPT = """You are an expert evaluator of UK REF (Research Excellence Framework) impact submissions.
Your task is to assess an institution's *overall submission* in a single Unit of Assessment — not any individual case study or academic.

You will be given:
- The official REF 2021 quality profile for this submission (percentages at 4*/3*/2*/1*/Unclassified for the Impact sub-profile).
- The full text of every impact case study the institution submitted to this UoA.

## What to evaluate

Look across the submission as a whole. Consider:
- **Thematic coherence** — Do the case studies tell a unified story, or are they scattered?
- **Reach diversity** — Local vs national vs international footprint across the portfolio.
- **Evidence patterns** — Does the institution consistently provide strong corroborating evidence, or are there recurring weaknesses (testimonial-heavy, missing quantification, weak causal chains)?
- **Significance ceiling** — How transformative is the highest-impact work, and how representative is it?
- **Portfolio balance** — Standout outliers versus consistent quality across submissions.

Frame strengths and weaknesses at the **submission/institutional level**, not the case-study level.
Do NOT name individual academics or critique a single case study in isolation.

## Output format

Respond with ONLY a valid JSON object:
{
  "university_key_strength": "<one sentence, 25-45 words, identifying the strongest pattern across the submission>",
  "university_key_weakness": "<one sentence, 25-45 words, identifying the most strategically important gap or weakness across the submission>",
  "assessment_notes": "<2-3 sentences explaining the rationale, referencing the score distribution and portfolio patterns>"
}"""

USER_PROMPT_TEMPLATE = """**Institution:** {institution}
**Unit of Assessment:** {uoa_code} – {uoa_name}

**Official REF 2021 Impact Quality Profile:**
{profile_summary}

**Number of impact case studies submitted to this UoA:** {n_case_studies}

---

{case_studies}

---

Assess this institution's overall submission to this UoA. Return only the JSON object."""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _extract_json(content: str) -> str:
    if '```' in content:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if m:
            return m.group(1)
    return content


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    with CACHE_PATH.open() as f:
        return json.load(f)


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open('w') as f:
        json.dump(cache, f, indent=2)


def _cache_key(university: str, uoa_code: str) -> str:
    return f"{university}||{uoa_code}"


def _format_profile(profile: dict | None) -> str:
    if not profile or 'impact' not in profile:
        return "Quality profile unavailable."
    imp = profile['impact']
    return (
        f"4*: {imp.get('4star', 0):.1f}% | 3*: {imp.get('3star', 0):.1f}% | "
        f"2*: {imp.get('2star', 0):.1f}% | 1*: {imp.get('1star', 0):.1f}% | "
        f"Unclassified: {imp.get('unclassified', 0):.1f}%"
    )


def _format_case_studies(case_studies: list[dict]) -> str:
    if not case_studies:
        return "No case study text available."
    blocks = []
    for i, cs in enumerate(case_studies, 1):
        title = cs.get('title') or f"Case study {i}"
        blocks.append(f"### Case Study {i}: {title}\n\n{cs.get('full_text', '')}")
    return '\n\n---\n\n'.join(blocks)


def aggregate_pair(university: str, uoa_code: str, uoa_name: str) -> dict | None:
    """Generate university-level strength + weakness for one (university, UoA) pair."""
    if not os.getenv('ANTHROPIC_API_KEY'):
        logger.warning("ANTHROPIC_API_KEY not set — skipping aggregation")
        return None

    profile = get_profile(university, uoa_code)
    case_studies = fetch_case_studies(university, uoa_code, uoa_name)

    if not case_studies and not profile:
        logger.warning(f"  No data for {university} / {uoa_code} — skipping")
        return None

    user_prompt = USER_PROMPT_TEMPLATE.format(
        institution=university,
        uoa_code=uoa_code,
        uoa_name=uoa_name or '',
        profile_summary=_format_profile(profile),
        n_case_studies=len(case_studies),
        case_studies=_format_case_studies(case_studies),
    )

    content = ''
    try:
        response = _get_client().messages.create(
            model='claude-opus-4-7',
            max_tokens=1024,
            system=[
                {
                    'type': 'text',
                    'text': SYSTEM_PROMPT,
                    'cache_control': {'type': 'ephemeral'},
                }
            ],
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        content = response.content[0].text.strip()
        result = json.loads(_extract_json(content))
        if profile:
            result['_profile'] = profile
        logger.info(f"  Aggregated {university} / {uoa_code}: strength + weakness produced")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {university}/{uoa_code}: {e}\nResponse: {content[:300]}")
        return None
    except anthropic.APIError as e:
        logger.error(f"Claude API error for {university}/{uoa_code}: {e}")
        return None


def aggregate_all(leads: list[dict], force: bool = False) -> dict:
    """
    Aggregate every distinct (university, uoa_code) pair across the lead set.
    Returns the full cache. Idempotent — skips pairs already cached unless force=True.
    """
    cache = {} if force else _load_cache()

    pairs: dict[tuple[str, str], str] = {}
    for lead in leads:
        uni = (lead.get('university') or '').strip()
        uoa = (lead.get('uoa_code') or '').strip()
        if not uni or not uoa:
            continue
        pairs[(uni, uoa)] = lead.get('uoa_name', '') or ''

    logger.info(f"University aggregation: {len(pairs)} distinct (university, UoA) pairs")

    for i, ((uni, uoa), uoa_name) in enumerate(sorted(pairs.items()), 1):
        key = _cache_key(uni, uoa)
        if key in cache and not force:
            logger.info(f"  [{i}/{len(pairs)}] {uni} / {uoa} — cached, skipping")
            continue
        logger.info(f"  [{i}/{len(pairs)}] {uni} / {uoa} — aggregating…")
        result = aggregate_pair(uni, uoa, uoa_name)
        if result is not None:
            cache[key] = result
            _save_cache(cache)

    return cache


def get_assessment(university: str, uoa_code: str) -> dict | None:
    """Look up a cached assessment for a (university, UoA) pair."""
    cache = _load_cache()
    return cache.get(_cache_key(university, uoa_code))
