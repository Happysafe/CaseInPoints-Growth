from __future__ import annotations
"""
Extracts structured fields from raw REF 2021 case study data.
Matches a case study to a specific lead where possible (by professor name).
"""
import re
from difflib import SequenceMatcher


def _first_n_sentences(text: str, n: int = 3) -> str:
    if not text:
        return ''
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return ' '.join(sentences[:n]).strip()


def _name_similarity(a: str, b: str) -> float:
    a_parts = set(a.lower().split())
    b_parts = set(b.lower().split())
    overlap = a_parts & b_parts
    if not overlap:
        return 0.0
    return len(overlap) / max(len(a_parts), len(b_parts))


def _extract_rating(text: str) -> str | None:
    """Find a star rating in text."""
    m = re.search(r'\b([1-4])\s*\*', text)
    if m:
        return f"{m.group(1)}*"
    if re.search(r'\bunclassified\b', text, re.I):
        return 'Unclassified'
    return None


def best_match_for_lead(lead: dict, case_studies: list[dict]) -> dict | None:
    """
    Given a lead and a list of case studies for that institution+UoA,
    return the best matching case study.
    If the lead is a professor, try to match by name.
    Otherwise, return the first case study (most relevant by search ranking).
    """
    if not case_studies:
        return None

    professor_name = lead.get('contact_name', '')

    if lead.get('role_type') == 'professor' and professor_name:
        best = None
        best_score = 0.0
        for cs in case_studies:
            score = _name_similarity(professor_name, cs.get('title', '') + ' ' + cs.get('institution', ''))
            if score > best_score:
                best_score = score
                best = cs
        # Only use name match if similarity is reasonable; otherwise fall back to first
        if best and best_score > 0.2:
            return best

    return case_studies[0]


def extract_structured(case_study: dict) -> dict:
    """
    From a raw case study dict, extract the fields we need for Notion + scoring.
    Returns a dict with: research_summary, impact_summary, evidence_summary, rating.
    """
    sections = case_study.get('sections', {})

    research_text = sections.get('Underpinning research', '')
    impact_text = sections.get('Details of the impact', '') or sections.get('Summary of the impact', '')
    evidence_text = sections.get('Sources to corroborate the impact', '')

    # Fall back to full_text if sections are empty
    if not research_text and not impact_text:
        full = case_study.get('full_text', '')
        research_text = full[:1000]
        impact_text = full[1000:2000]

    rating = (
        _extract_rating(case_study.get('rating', '')) or
        _extract_rating(case_study.get('full_text', ''))
    )

    return {
        'research_summary': _first_n_sentences(research_text, 3),
        'impact_summary': _first_n_sentences(impact_text, 3),
        'evidence_summary': _first_n_sentences(evidence_text, 2),
        'ref_2021_rating': rating or 'Unknown',
        'case_study_url': case_study.get('url', ''),
        'case_study_title': case_study.get('title', ''),
    }
