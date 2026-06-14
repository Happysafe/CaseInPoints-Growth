from __future__ import annotations

import json
import re
from pathlib import Path


_DATA_PATH = Path(__file__).parent.parent / 'data' / 'uoa_lookup.json'
_LOOKUP: list[dict] | None = None

# Minimum number of matching keywords required to accept a UoA match
MIN_KEYWORD_MATCHES = 1


def _load_lookup() -> list[dict]:
    global _LOOKUP
    if _LOOKUP is None:
        with open(_DATA_PATH) as f:
            raw = json.load(f)['keywords']
        # Pre-compile a regex for each keyword so infer_uoa doesn't recompile on every call
        for entry in raw:
            entry['_patterns'] = [
                re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
                for kw in entry['keywords']
            ]
        _LOOKUP = raw
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
    best_keywords: list[str] = []

    for entry in lookup:
        matched = [
            kw for kw, pattern in zip(entry['keywords'], entry['_patterns'])
            if pattern.search(text)
        ]
        # Weight by total character length so longer (more specific) keywords win ties
        weighted = sum(len(kw) for kw in matched)
        if weighted > best_score:
            best_score = weighted
            best = entry
            best_keywords = matched

    if best and len(best_keywords) >= MIN_KEYWORD_MATCHES:
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
