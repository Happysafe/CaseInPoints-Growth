"""
Profile enrichment via ORCID and Semantic Scholar APIs.
Only runs for leads with role_type == 'professor'.
"""
from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

ORCID_SEARCH_URL = "https://pub.orcid.org/v3.0/search/"
SS_AUTHOR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/author/search"

_SS_API_KEY = os.getenv('SEMANTIC_SCHOLAR_KEY', '')
# Authenticated requests allow 100 req/s; unauthenticated cap is 1 req/s.
REQUEST_DELAY = 0.05 if _SS_API_KEY else 1.1

ORCID_HEADERS = {
    'Accept': 'application/json',
    'User-Agent': 'REFImpactPipeline/1.0 (contact: research@caseinpoints.com)',
}

SS_HEADERS = {'x-api-key': _SS_API_KEY} if _SS_API_KEY else {}


def _get(url: str, params: dict = None, headers: dict = None, timeout: int = 20) -> dict | None:
    try:
        resp = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        logger.warning(f"HTTP {e.response.status_code} for {url}")
        return None
    except requests.RequestException as e:
        logger.warning(f"Request error {url}: {e}")
        return None
    except ValueError:
        logger.warning(f"JSON decode error for {url}")
        return None
    finally:
        time.sleep(REQUEST_DELAY)


def _split_name(full_name: str) -> tuple[str, str]:
    """Split 'Professor Jane Smith' or 'Dr John Doe' into first, last."""
    # Strip titles
    clean = full_name.strip()
    for title in ['Professor ', 'Prof. ', 'Prof ', 'Dr. ', 'Dr ', 'Mr ', 'Ms ', 'Mrs ', 'Sir ']:
        if clean.startswith(title):
            clean = clean[len(title):]
    parts = clean.split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return clean, ''


def enrich_orcid(contact_name: str, university: str) -> dict:
    """
    Search ORCID for a researcher by name and institution.
    Returns {orcid_id, works_count} or empty dict.
    """
    first, last = _split_name(contact_name)
    if not last:
        return {}

    query_parts = []
    if last:
        query_parts.append(f'family-name:{last}')
    if first:
        query_parts.append(f'given-names:{first}')
    if university:
        # Use just the first word of university to avoid over-constraining
        uni_word = university.split()[0]
        query_parts.append(f'affiliation-org-name:{uni_word}')

    query = ' AND '.join(query_parts)
    data = _get(ORCID_SEARCH_URL, params={'q': query, 'rows': 3}, headers=ORCID_HEADERS)

    if not data:
        return {}

    results = data.get('result', [])
    if not results:
        return {}

    # Take the first result
    record = results[0]
    orcid_id = (
        record.get('orcid-identifier', {}).get('path') or
        record.get('orcid-identifier', {}).get('uri', '').split('/')[-1]
    )

    return {'orcid_id': orcid_id} if orcid_id else {}


def enrich_semantic_scholar(contact_name: str) -> dict:
    """
    Search Semantic Scholar for a researcher.
    Returns {semantic_scholar_id, h_index, citation_count, top_paper} or empty dict.
    """
    first, last = _split_name(contact_name)
    query = f"{first} {last}".strip()

    data = _get(
        SS_AUTHOR_SEARCH_URL,
        params={
            'query': query,
            'fields': 'name,hIndex,citationCount',
            'limit': 3,
        },
        headers=SS_HEADERS,
    )

    if not data:
        return {}

    authors = data.get('data', [])
    if not authors:
        return {}

    # Pick the author with highest citation count (most likely the right person)
    author = max(authors, key=lambda a: a.get('citationCount', 0) or 0)
    author_id = author.get('authorId', '')

    top_paper = ''
    if author_id:
        papers_data = _get(
            f'https://api.semanticscholar.org/graph/v1/author/{author_id}/papers',
            params={'fields': 'title,citationCount', 'limit': 5},
            headers=SS_HEADERS,
        )
        if papers_data:
            papers = papers_data.get('data', [])
            if papers:
                best = max(papers, key=lambda p: p.get('citationCount', 0) or 0)
                top_paper = best.get('title', '')

    return {
        'semantic_scholar_id': author_id,
        'h_index': author.get('hIndex'),
        'citation_count': author.get('citationCount'),
        'top_paper': top_paper,
    }


def enrich_lead(lead: dict) -> dict:
    """
    Enrich a lead with ORCID and Semantic Scholar data.
    Only runs full enrichment for professors; skips API calls for admin contacts.
    Returns the lead dict with enrichment fields added in-place.
    """
    if lead.get('role_type') != 'professor':
        logger.info(f"Skipping API enrichment for admin contact: {lead['contact_name']}")
        return lead

    contact_name = lead.get('contact_name', '')
    university = lead.get('university', '')

    logger.info(f"Enriching {contact_name} via ORCID + Semantic Scholar")
    lead.update(enrich_orcid(contact_name, university))
    lead.update(enrich_semantic_scholar(contact_name))

    return lead
