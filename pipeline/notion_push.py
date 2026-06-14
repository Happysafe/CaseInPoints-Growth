"""
Notion CRM push — creates the database schema on first run, then pushes lead records.
"""
from __future__ import annotations

import logging
import os

import requests

from pipeline.ref_results_scraper import get_university_profile
from pipeline.university_aggregator import get_assessment
from pipeline.university_category import classify_university

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# Schema definition — maps property name to Notion type config
SCHEMA = {
    "University":          {"rich_text": {}},
    "Department":          {"rich_text": {}},
    "Unit of Assessment":  {"rich_text": {}},
    "REF 2021 Rating":     {"select": {"options": [
        {"name": "4*"}, {"name": "3*"}, {"name": "2*"},
        {"name": "1*"}, {"name": "Unclassified"}, {"name": "Unknown"},
    ]}},
    "Research Theme":      {"rich_text": {}},
    "Impact Summary":      {"rich_text": {}},
    "Key Weakness":        {"rich_text": {}},
    "University Key Strength": {"rich_text": {}},
    "2021 Impact 4*":      {"number": {"format": "percent"}},
    "2021 Impact 3*":      {"number": {"format": "percent"}},
    "2021 Impact 2*":      {"number": {"format": "percent"}},
    "2021 Impact 1*":      {"number": {"format": "percent"}},
    "2021 Impact Unclassified": {"number": {"format": "percent"}},
    "2014 Impact 4*":      {"number": {"format": "percent"}},
    "2014 Impact 3*":      {"number": {"format": "percent"}},
    "2014 Impact 2*":      {"number": {"format": "percent"}},
    "2014 Impact 1*":      {"number": {"format": "percent"}},
    "2014 Impact Unclassified": {"number": {"format": "percent"}},
    "Email":               {"email": {}},
    "LinkedIn":            {"url": {}},
    "ORCID ID":            {"rich_text": {}},
    "Semantic Scholar ID": {"rich_text": {}},
    "H-Index":             {"number": {"format": "number"}},
    "Top Paper":           {"rich_text": {}},
    "Stage":               {"select": {"options": [
        {"name": "Identified"}, {"name": "Contacted"}, {"name": "Engaged"},
        {"name": "Trial"}, {"name": "Meeting"}, {"name": "Closed"}, {"name": "Dead"},
    ]}},
    "Last Touch":          {"date": {}},
    "Notes":               {"rich_text": {}},
    "Next Action":         {"rich_text": {}},
    "Pre-Analysis File":   {"url": {}},
    "Calendly Link Sent":  {"checkbox": {}},
    "Trial Completed":     {"checkbox": {}},
    "Outreach Tier":       {"select": {"options": [
        {"name": "1"}, {"name": "2"}, {"name": "3"}, {"name": "?"},
    ]}},
    "UoA Impact Mean":     {"number": {"format": "number"}},
    "University Category": {"select": {"options": [
        {"name": "Leaders"}, {"name": "Improvers"},
        {"name": "Stagnant"}, {"name": "At Risk"},
    ]}},
    "Change in 4*":        {"number": {"format": "percent"}},
    "Change in 3*+":       {"number": {"format": "percent"}},
}

_schema_initialised = False

# Legacy → current property renames applied to existing databases on first push.
_RENAMES = {
    "REF Impact 4*":           "2021 Impact 4*",
    "REF Impact 3*":           "2021 Impact 3*",
    "REF Impact 2*":           "2021 Impact 2*",
    "REF Impact 1*":           "2021 Impact 1*",
    "REF Impact Unclassified": "2021 Impact Unclassified",
}
# Legacy properties to remove entirely (deletes their values too). "REF Scope"
# is dropped now that all rows are university-wide (so 2014 and 2021 are comparable).
_DELETIONS = ("Pre-Score", "REF Overall GPA", "REF Scope")


def _headers(token: str) -> dict:
    return {
        'Authorization': f'Bearer {token}',
        'Notion-Version': NOTION_API_VERSION,
        'Content-Type': 'application/json',
    }


# --- Notion property serialisers ---

def _text_prop(value) -> dict:
    return {'rich_text': [{'type': 'text', 'text': {'content': str(value or '')[:2000]}}]}


def _select_prop(value) -> dict:
    return {'select': {'name': str(value)[:100]}} if value else {'select': None}


def _number_prop(value) -> dict:
    return {'number': float(value)} if value is not None else {'number': None}


def _none_prop(key: str, value) -> dict:
    """Generic serialiser for url and email properties — both follow the same shape."""
    v = str(value).strip() if value else ''
    return {key: v} if v else {key: None}


def pp_to_percent(value: float | None) -> float | None:
    """Percentage points (0–100) → Notion 'percent' format (0–1), rounded to 4dp."""
    return round(value / 100, 4) if value is not None else None


# ---


def setup_schema(token: str, database_id: str) -> bool:
    """
    Ensure all required properties exist in the Notion database.
    Adds any missing columns; leaves existing ones untouched.
    Called once before the first push.
    """
    r = requests.get(
        f"{NOTION_BASE_URL}/databases/{database_id}",
        headers=_headers(token), timeout=20,
    )
    if not r.ok:
        logger.error(f"Could not fetch database schema: {r.status_code} {r.text[:200]}")
        return False

    existing = set(r.json().get('properties', {}).keys())

    # Migrate legacy properties first: rename old Impact columns and delete
    # dropped ones. Renames preserve the populated percentage values; this is a
    # no-op on a fresh database (none of these properties exist yet).
    migration: dict = {}
    for old, new in _RENAMES.items():
        if old in existing and new not in existing:
            migration[old] = {'name': new}
    for prop in _DELETIONS:
        if prop in existing:
            migration[prop] = None

    if migration:
        logger.info(f"Migrating Notion properties: {list(migration.keys())}")
        mig = requests.patch(
            f"{NOTION_BASE_URL}/databases/{database_id}",
            headers=_headers(token),
            json={'properties': migration},
            timeout=20,
        )
        if not mig.ok:
            logger.error(f"Schema migration failed: {mig.status_code} {mig.text[:300]}")
            return False
        # Reflect renames/deletions in the in-memory set before adding columns.
        for old, new in _RENAMES.items():
            if old in existing:
                existing.discard(old)
                existing.add(new)
        existing -= set(_DELETIONS)

    missing = {k: v for k, v in SCHEMA.items() if k not in existing}

    if not missing:
        logger.info("Notion schema already complete")
        return True

    logger.info(f"Adding {len(missing)} missing columns to Notion database: {list(missing.keys())}")
    patch = requests.patch(
        f"{NOTION_BASE_URL}/databases/{database_id}",
        headers=_headers(token),
        json={'properties': missing},
        timeout=20,
    )
    if not patch.ok:
        logger.error(f"Schema update failed: {patch.status_code} {patch.text[:300]}")
        return False

    logger.info("Notion schema updated successfully")
    return True


def fetch_page_ids_by_name(token: str, database_id: str) -> dict:
    """
    Map page title (Name) -> page_id for all non-archived pages in the database.
    Used to backfill `notion_page_id` so refreshes UPDATE existing pages instead
    of creating duplicates. On duplicate titles the first page seen wins (logged).
    """
    out: dict[str, str] = {}
    dupes: set[str] = set()
    cursor = None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        r = requests.post(
            f"{NOTION_BASE_URL}/databases/{database_id}/query",
            headers=_headers(token), json=body, timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        for page in j.get('results', []):
            title = page.get('properties', {}).get('Name', {}).get('title', [])
            name = title[0]['plain_text'] if title else ''
            if not name:
                continue
            if name in out:
                dupes.add(name)
            else:
                out[name] = page['id']
        if not j.get('has_more'):
            break
        cursor = j['next_cursor']
    if dupes:
        logger.warning(f"Duplicate page titles in Notion (first kept): {sorted(dupes)}")
    return out


def _impact_pcts(impact: dict, prefix: str) -> dict:
    """Map an Impact distribution (0–100) to Notion percent props (0–1) under a year prefix."""
    def pct(key):
        return pp_to_percent(impact.get(key, 0)) if impact else None
    return {
        f'{prefix}_4star': pct('4star'),
        f'{prefix}_3star': pct('3star'),
        f'{prefix}_2star': pct('2star'),
        f'{prefix}_1star': pct('1star'),
        f'{prefix}_unclassified': pct('unclassified'),
    }


def _university_fields(lead: dict) -> dict:
    """
    Resolve university-level fields for a lead: the university-wide Impact
    distribution for both REF exercises (2014 and 2021), plus University Key
    Strength and (repurposed) Key Weakness.

    The Impact distributions are always the institution's university-wide mean
    (across all its UoAs) for BOTH years, so 2014 and 2021 are directly
    comparable. The strength/weakness text remains UoA-specific (Claude-generated)
    and stays blank for leads with no inferred UoA.
    """
    uni = lead.get('university', '')
    uoa = lead.get('uoa_code', '')

    assessment = get_assessment(uni, uoa) or {}
    impact_2021 = (get_university_profile(uni, 2021) or {}).get('impact') or {}
    impact_2014 = (get_university_profile(uni, 2014) or {}).get('impact') or {}
    category, metrics = classify_university(uni)

    return {
        'university_key_strength': assessment.get('university_key_strength', ''),
        'university_key_weakness': assessment.get('university_key_weakness', ''),
        'university_category': category,
        'change_in_4star': pp_to_percent(metrics.get('delta_4star')),
        'change_in_3star_plus': pp_to_percent(metrics.get('delta_3star_plus')),
        **_impact_pcts(impact_2021, 'impact_2021'),
        **_impact_pcts(impact_2014, 'impact_2014'),
    }


def _build_properties(lead: dict, include_stage: bool = True) -> dict:
    """
    Build the Notion `properties` dict for a lead. Shared between create (POST)
    and update (PATCH) paths.
    """
    uoa_label = f"{lead.get('uoa_code', '')} – {lead.get('uoa_name', '')}".strip(' –') or 'Unknown'
    u = _university_fields(lead)

    props = {
        'Name':                {'title': [{'type': 'text', 'text': {'content': str(lead.get('contact_name', ''))[:2000]}}]},
        'University':          _text_prop(lead.get('university')),
        'Department':          _text_prop(lead.get('department')),
        'Unit of Assessment':  _text_prop(uoa_label),
        'REF 2021 Rating':     _select_prop(lead.get('ref_2021_rating') or 'Unknown'),
        'Research Theme':      _text_prop(lead.get('research_summary')),
        'Impact Summary':      _text_prop(lead.get('impact_summary')),
        'Key Weakness':        _text_prop(u['university_key_weakness']),
        'University Key Strength': _text_prop(u['university_key_strength']),
        'University Category': _select_prop(u['university_category']),
        'Change in 4*':        _number_prop(u['change_in_4star']),
        'Change in 3*+':       _number_prop(u['change_in_3star_plus']),
        '2021 Impact 4*':      _number_prop(u['impact_2021_4star']),
        '2021 Impact 3*':      _number_prop(u['impact_2021_3star']),
        '2021 Impact 2*':      _number_prop(u['impact_2021_2star']),
        '2021 Impact 1*':      _number_prop(u['impact_2021_1star']),
        '2021 Impact Unclassified': _number_prop(u['impact_2021_unclassified']),
        '2014 Impact 4*':      _number_prop(u['impact_2014_4star']),
        '2014 Impact 3*':      _number_prop(u['impact_2014_3star']),
        '2014 Impact 2*':      _number_prop(u['impact_2014_2star']),
        '2014 Impact 1*':      _number_prop(u['impact_2014_1star']),
        '2014 Impact Unclassified': _number_prop(u['impact_2014_unclassified']),
        'Email':               _none_prop('email', lead.get('email')),
        'LinkedIn':            _none_prop('url', lead.get('linkedin')),
        'ORCID ID':            _text_prop(lead.get('orcid_id')),
        'Semantic Scholar ID': _text_prop(lead.get('semantic_scholar_id')),
        'H-Index':             _number_prop(lead.get('h_index')),
        'Top Paper':           _text_prop(lead.get('top_paper')),
    }
    if include_stage:
        props['Stage'] = _select_prop('Identified')
        props['Calendly Link Sent'] = {'checkbox': False}
        props['Trial Completed'] = {'checkbox': False}
    return props


def _build_payload(lead: dict, database_id: str) -> dict:
    return {
        'parent': {'database_id': database_id},
        'properties': _build_properties(lead, include_stage=True),
    }


def push_to_notion(lead: dict) -> str | None:
    """
    Upsert a lead into Notion. If `lead['notion_page_id']` is set, PATCH that page;
    otherwise create a new page.
    """
    global _schema_initialised

    token = os.getenv('NOTION_TOKEN', '')
    database_id = os.getenv('NOTION_DATABASE_ID', '')

    if not token or not database_id:
        logger.warning("Notion credentials not set — skipping push")
        return None

    if not _schema_initialised:
        setup_schema(token, database_id)
        _schema_initialised = True

    existing_page_id = lead.get('notion_page_id')

    try:
        if existing_page_id:
            resp = requests.patch(
                f"{NOTION_BASE_URL}/pages/{existing_page_id}",
                headers=_headers(token),
                json={'properties': _build_properties(lead, include_stage=False)},
                timeout=20,
            )
            resp.raise_for_status()
            logger.info(f"Updated Notion page: {existing_page_id}")
            return existing_page_id

        resp = requests.post(
            f"{NOTION_BASE_URL}/pages",
            headers=_headers(token),
            json=_build_payload(lead, database_id),
            timeout=20,
        )
        resp.raise_for_status()
        page_id = resp.json().get('id', '')
        logger.info(f"Created Notion page: {page_id}")
        return page_id
    except requests.RequestException as e:
        logger.error(f"Notion API error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response body: {e.response.text[:300]}")
        return None
