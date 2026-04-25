from __future__ import annotations

import json
import os
import re


_DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'uoa_lookup.json')
_LOOKUP: list[dict] | None = None

CONFIDENCE_THRESHOLD = 1  # at least 1 keyword must match


def _load_lookup() -> list[dict]:
    global _LOOKUP
    if _LOOKUP is None:
        with open(_DATA_PATH) as f:
            _LOOKUP = json.load(f)['keywords']
    return _LOOKUP


def infer_uoa(position: str, university: str = '') -> dict:
    """
    Returns: {uoa_code, uoa_name, panel, confidence, matched_keywords}
    confidence = number of matching keywords found.
    Returns {uoa_code: None, ...} if no match above threshold.
    """
    lookup = _load_lookup()
    text = (position + ' ' + university).lower()

    best = None
    best_score = 0
    best_keywords = []

    for entry in lookup:
        matched = []
        for kw in entry['keywords']:
            pattern = re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
            if pattern.search(text):
                matched.append(kw)
        score = len(matched)
        # Prefer longer keyword matches (more specific)
        weighted = sum(len(kw) for kw in matched)
        if weighted > best_score:
            best_score = weighted
            best = entry
            best_keywords = matched

    if best and len(best_keywords) >= CONFIDENCE_THRESHOLD:
        return {
            'uoa_code': best['uoa_code'],
            'uoa_name': best['uoa_name'],
            'panel': best['panel'],
            'confidence': len(best_keywords),
            'matched_keywords': best_keywords,
        }

    return {
        'uoa_code': None,
        'uoa_name': 'Unknown',
        'panel': None,
        'confidence': 0,
        'matched_keywords': [],
    }
