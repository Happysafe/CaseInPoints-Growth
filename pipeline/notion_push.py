"""
Notion CRM push — creates the database schema on first run, then pushes lead records.
"""
from __future__ import annotations

import json
import logging
import os

import requests

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
    "Pre-Score":           {"number": {"format": "number"}},
    "Research Theme":      {"rich_text": {}},
    "Impact Summary":      {"rich_text": {}},
    "Key Weakness":        {"rich_text": {}},
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
}

_schema_initialised = False


def _headers(token: str) -> dict:
    return {
        'Authorization': f'Bearer {token}',
        'Notion-Version': NOTION_API_VERSION,
        'Content-Type': 'application/json',
    }


def setup_schema(token: str, database_id: str) -> bool:
    """
    Ensure all required properties exist in the Notion database.
    Adds any missing columns; leaves existing ones untouched.
    Called once before the first push.
    """
    # Fetch current schema
    r = requests.get(
        f"{NOTION_BASE_URL}/databases/{database_id}",
        headers=_headers(token), timeout=20,
    )
    if not r.ok:
        logger.error(f"Could not fetch database schema: {r.status_code} {r.text[:200]}")
        return False

    existing = set(r.json().get('properties', {}).keys())
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


def _build_payload(lead: dict, database_id: str) -> dict:

    def text(value):
        content = str(value or '')[:2000]  # Notion rich_text limit
        return {'rich_text': [{'type': 'text', 'text': {'content': content}}]}

    def select(value):
        return {'select': {'name': str(value)[:100]}} if value else {'select': None}

    def number(value):
        return {'number': float(value)} if value is not None else {'number': None}

    def url_prop(value):
        v = str(value).strip() if value else ''
        return {'url': v} if v else {'url': None}

    def email_prop(value):
        v = str(value).strip() if value else ''
        return {'email': v} if v else {'email': None}

    scores = lead.get('scores') or {}
    uoa_label = f"{lead.get('uoa_code', '')} – {lead.get('uoa_name', '')}".strip(' –') or 'Unknown'

    return {
        'parent': {'database_id': database_id},
        'properties': {
            'Name':                {'title': [{'type': 'text', 'text': {'content': str(lead.get('contact_name', ''))[:2000]}}]},
            'University':          text(lead.get('university')),
            'Department':          text(lead.get('department')),
            'Unit of Assessment':  text(uoa_label),
            'REF 2021 Rating':     select(lead.get('ref_2021_rating') or 'Unknown'),
            'Pre-Score':           number(scores.get('overall_score') or lead.get('pre_score')),
            'Research Theme':      text(lead.get('research_summary')),
            'Impact Summary':      text(lead.get('impact_summary')),
            'Key Weakness':        text(lead.get('key_weakness')),
            'Email':               email_prop(lead.get('email')),
            'LinkedIn':            url_prop(lead.get('linkedin')),
            'ORCID ID':            text(lead.get('orcid_id')),
            'Semantic Scholar ID': text(lead.get('semantic_scholar_id')),
            'H-Index':             number(lead.get('h_index')),
            'Top Paper':           text(lead.get('top_paper')),
            'Stage':               select('Identified'),
            'Calendly Link Sent':  {'checkbox': False},
            'Trial Completed':     {'checkbox': False},
        },
    }


def push_to_notion(lead: dict) -> str | None:
    global _schema_initialised

    token = os.getenv('NOTION_TOKEN', '')
    database_id = os.getenv('NOTION_DATABASE_ID', '')

    if not token or not database_id:
        logger.warning("Notion credentials not set — skipping push")
        return None

    if not _schema_initialised:
        setup_schema(token, database_id)
        _schema_initialised = True

    payload = _build_payload(lead, database_id)
    try:
        resp = requests.post(
            f"{NOTION_BASE_URL}/pages",
            headers=_headers(token),
            json=payload,
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
