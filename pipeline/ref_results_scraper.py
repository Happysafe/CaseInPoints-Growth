"""
REF quality profile lookup — uses the official downloaded results spreadsheets.

Supports two exercises:
- 2021: data/ref2021_results_all.xlsx (source: https://results2021.ref.ac.uk/profiles/export-all)
- 2014: data/ref2014_results_all.xlsx (source: https://results.ref.ac.uk/DownloadResults)

Each (institution × UoA) submission has four profile rows: Overall, Outputs,
Impact, Environment — each with percentages for 4*/3*/2*/1*/Unclassified.

NB the two files differ in layout: the 2021 header row is 6 and its unclassified
column is "Unclassified"; the 2014 header row is 7 and it is "unclassified".
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pipeline.ref_scraper import _institution_similarity

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / 'data'
DEFAULT_YEAR = 2021

# Per-exercise source layout. `header` is the 0-based row holding the real column
# headers; `unclassified_col` is that file's spelling of the unclassified column.
_YEARS = {
    2021: {
        'data': _DATA_DIR / 'ref2021_results_all.xlsx',
        'cache': _DATA_DIR / 'ref2021_results_profiles.json',
        'header': 6,
        'unclassified_col': 'Unclassified',
    },
    2014: {
        'data': _DATA_DIR / 'ref2014_results_all.xlsx',
        'cache': _DATA_DIR / 'ref2014_results_profiles.json',
        'header': 7,
        'unclassified_col': 'unclassified',
    },
}

_RATING_KEYS = ['4star', '3star', '2star', '1star', 'unclassified']

# In-memory index per year, keyed by (institution_name, uoa_int).
_profiles_cache: dict[int, dict] = {}

# Minimum similarity for a fuzzy institution match. Below this (or on a tie with
# the runner-up) we return None rather than guess wrong. Names that fuzzy-match
# poorly because the official REF name differs are handled by _ALIASES instead.
_MATCH_THRESHOLD = 0.6

# Lead university name (normalised) -> exact institution name in a REF results file.
# These don't fuzzy-match reliably in the 2021 file: Imperial's official name omits
# "London", and "Newcastle University" otherwise loses to "Northumbria at Newcastle".
# When the alias target isn't present for a given year (the 2014 file uses the plain
# names), matching falls through to fuzzy, which resolves them there.
_ALIASES = {
    'imperial college london': 'Imperial College of Science, Technology and Medicine',
    'newcastle university': 'University of Newcastle upon Tyne',
}


def quality_mean(dist: dict | None) -> float:
    """
    Weighted GPA mean (0–4) of a quality distribution keyed 4star..1star.
    Percentages are on a 0–100 scale; unclassified contributes 0.
    """
    if not dist:
        return 0.0
    return (
        4 * dist.get('4star', 0.0)
        + 3 * dist.get('3star', 0.0)
        + 2 * dist.get('2star', 0.0)
        + 1 * dist.get('1star', 0.0)
    ) / 100


def _normalise(name: str) -> str:
    s = re.sub(r'[^a-z0-9 ]', ' ', (name or '').lower())
    s = re.sub(r'\s+', ' ', s).strip()
    return s[4:] if s.startswith('the ') else s


def _load_profiles(year: int = DEFAULT_YEAR) -> dict:
    """Load and index a year's REF results spreadsheet, keyed by (institution, uoa_int)."""
    if year in _profiles_cache:
        return _profiles_cache[year]

    cfg = _YEARS.get(year)
    if cfg is None:
        logger.error(f"No REF results config for year {year}")
        _profiles_cache[year] = {}
        return _profiles_cache[year]

    cache_path = cfg['cache']
    if cache_path.exists():
        with cache_path.open() as f:
            raw = json.load(f)
        index = {}
        for k, v in raw.items():
            inst, uoa_str = k.split('||')
            index[(inst, int(uoa_str))] = v
        logger.info(f"Loaded REF {year} results cache: {len(index)} (institution, UoA) submissions")
        _profiles_cache[year] = index
        return index

    import pandas as pd

    if not cfg['data'].exists():
        logger.error(f"REF {year} results file not found at {cfg['data']}")
        _profiles_cache[year] = {}
        return _profiles_cache[year]

    rating_cols = ['4*', '3*', '2*', '1*', cfg['unclassified_col']]
    df = pd.read_excel(cfg['data'], header=cfg['header'])
    df = df.dropna(subset=['Institution name', 'Unit of assessment number', 'Profile'])

    index: dict[tuple[str, int], dict[str, dict[str, float]]] = {}
    for row in df.to_dict('records'):
        inst = str(row['Institution name']).strip()
        try:
            uoa_num = int(row['Unit of assessment number'])
        except (ValueError, TypeError):
            continue
        profile = str(row['Profile']).strip().lower()
        if profile not in {'overall', 'outputs', 'impact', 'environment'}:
            continue

        ratings = {}
        for key, col in zip(_RATING_KEYS, rating_cols):
            try:
                ratings[key] = float(row[col])
            except (ValueError, TypeError):
                ratings[key] = 0.0

        key = (inst, uoa_num)
        if key not in index:
            index[key] = {'uoa_name': str(row.get('Unit of assessment name', '')).strip()}
        index[key][profile] = ratings

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {f"{k[0]}||{k[1]}": v for k, v in index.items()}
    with cache_path.open('w') as f:
        json.dump(serializable, f, indent=2)
    logger.info(f"Cached REF {year} results profiles to {cache_path} ({len(index)} submissions)")

    _profiles_cache[year] = index
    return index


def _match_institution(lead_university: str, known_institutions: list[str]) -> str | None:
    alias = _ALIASES.get(_normalise(lead_university))
    if alias and alias in known_institutions:
        return alias

    best, best_score, second_score = None, 0.0, 0.0
    for inst in known_institutions:
        score = _institution_similarity(lead_university, inst)
        if score > best_score:
            best, best_score, second_score = inst, score, best_score
        elif score > second_score:
            second_score = score

    # Reject weak matches and ambiguous ties (e.g. several London universities at 0.5).
    if best is None or best_score < _MATCH_THRESHOLD or best_score <= second_score:
        return None
    return best


def get_profile(university: str, uoa_code: str, year: int = DEFAULT_YEAR) -> dict | None:
    """
    Return quality profile dict for a (university, UoA) pair, or None if not found.

    Structure:
        {
          "uoa_name": "Engineering",
          "overall": {"4star": 50.0, "3star": 30.0, "2star": 15.0, "1star": 5.0, "unclassified": 0.0},
          "outputs": {...},
          "impact":  {...},
          "environment": {...},
          "overall_gpa": 3.30
        }
    """
    profiles = _load_profiles(year)
    if not profiles:
        return None

    try:
        uoa_int = int(str(uoa_code).replace('UoA', '').strip())
    except ValueError:
        logger.warning(f"Could not parse UoA code: {uoa_code!r}")
        return None

    institutions = sorted({k[0] for k in profiles.keys()})
    matched = _match_institution(university, institutions)
    if matched is None:
        logger.warning(f"No REF {year} results institution match for '{university}'")
        return None

    entry = profiles.get((matched, uoa_int))
    if entry is None:
        logger.warning(f"No REF {year} results submission for '{matched}' UoA {uoa_int}")
        return None

    gpa = quality_mean(entry.get('overall'))

    return {**entry, 'matched_institution': matched, 'overall_gpa': round(gpa, 2)}


def get_university_profile(university: str, year: int = DEFAULT_YEAR, profile: str = 'impact') -> dict | None:
    """
    University-wide distribution for one sub-profile: the unweighted mean of that
    sub-profile ('impact', 'overall', 'outputs', 'environment') across every UoA
    the institution submitted in that exercise.

    Returns {<profile>: {4star..unclassified}, "matched_institution": str, "n_uoas": int}
    or None if the institution can't be matched. The result is keyed by the
    requested sub-profile name (so the default keeps the historic "impact" key).
    """
    profiles = _load_profiles(year)
    if not profiles:
        return None

    institutions = sorted({k[0] for k in profiles.keys()})
    matched = _match_institution(university, institutions)
    if matched is None:
        logger.warning(f"No REF {year} results institution match for '{university}' (university-wide)")
        return None

    acc = {key: 0.0 for key in _RATING_KEYS}
    n = 0
    for (inst, _uoa), entry in profiles.items():
        if inst != matched:
            continue
        dist = entry.get(profile)
        if dist:
            n += 1
            for key in _RATING_KEYS:
                acc[key] += dist.get(key, 0)

    if n == 0:
        return None

    mean = {key: round(acc[key] / n, 1) for key in _RATING_KEYS}
    return {profile: mean, 'matched_institution': matched, 'n_uoas': n}


def warm_cache() -> int:
    """Force-load every configured year's cache. Returns total submissions indexed."""
    return sum(len(_load_profiles(year)) for year in _YEARS)
