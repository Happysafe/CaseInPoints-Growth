"""
REF 2021 impact case study lookup — uses locally cached bulk export.
The full dataset is downloaded once to data/ref2021_impact_all.xlsx.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).parent.parent / 'data' / 'ref2021_impact_all.xlsx'

_df = None
_institutions: list[str] = []  # cached after first load

_SECTION_COLS = {
    'Summary of the impact':          '1. Summary of the impact',
    'Underpinning research':          '2. Underpinning research',
    'References to the research':     '3. References to the research',
    'Details of the impact':          '4. Details of the impact',
    'Sources to corroborate the impact': '5. Sources to corroborate the impact',
}


def _load_dataset():
    global _df, _institutions
    if _df is not None:
        return _df

    try:
        import pandas as pd
        _df = pd.read_excel(DATA_PATH)
        _institutions = _df['Institution name'].dropna().unique().tolist()
        logger.info(f"Loaded REF 2021 dataset: {len(_df)} case studies, {len(_institutions)} institutions")
        return _df
    except FileNotFoundError:
        logger.error(f"REF dataset not found at {DATA_PATH}. Run: python download_ref_data.py")
        return None
    except Exception as e:
        logger.error(f"Failed to load REF dataset: {e}")
        return None


def _institution_similarity(lead_name: str, ref_name: str) -> float:
    """Score how closely a lead university name matches a REF institution name."""
    a = lead_name.lower().strip()
    b = ref_name.lower().strip()

    if a == b or a in b or b in a:
        return 1.0

    stopwords = {'university', 'of', 'the', 'and', 'college', 'school'}
    a_words = set(re.findall(r'\b[a-z]{3,}\b', a)) - stopwords
    b_words = set(re.findall(r'\b[a-z]{3,}\b', b)) - stopwords

    if not a_words or not b_words:
        return 0.0

    return len(a_words & b_words) / max(len(a_words), len(b_words))


def _clean(val) -> str:
    s = str(val or '').strip()
    return '' if s == 'nan' else s


def fetch_case_studies(university: str, uoa_code: str | None, uoa_name: str | None) -> list[dict]:
    """
    Return matching case studies from the local dataset for the given
    institution and (optionally) unit of assessment.
    Each returned dict has: title, institution, uoa, full_text, sections.
    """
    df = _load_dataset()
    if df is None:
        return []

    best_inst = None
    best_score = 0.0
    for inst in _institutions:
        score = _institution_similarity(university, inst)
        if score > best_score:
            best_score = score
            best_inst = inst

    if best_inst is None or best_score < 0.3:
        logger.warning(f"No institution match for '{university}' (best score: {best_score:.2f})")
        return []

    logger.info(f"  Matched '{university}' → '{best_inst}' (score={best_score:.2f})")
    filtered = df[df['Institution name'] == best_inst]

    if uoa_code:
        uoa_num = uoa_code.replace('UoA ', '').strip()
        try:
            uoa_int = int(uoa_num)
            uoa_filtered = filtered[filtered['Unit of assessment number'] == uoa_int]
            if not uoa_filtered.empty:
                filtered = uoa_filtered
                logger.info(f"  Filtered to UoA {uoa_int}: {len(filtered)} case studies")
        except ValueError:
            pass
    elif uoa_name:
        name_filtered = filtered[
            filtered['Unit of assessment name'].str.contains(
                uoa_name.split(',')[0][:20], case=False, na=False
            )
        ]
        if not name_filtered.empty:
            filtered = name_filtered

    results = []
    for row in filtered.to_dict('records'):
        sections = {
            label: _clean(row.get(col))
            for label, col in _SECTION_COLS.items()
        }

        full_text = '\n\n'.join(f"### {k}\n{v}" for k, v in sections.items() if v)
        if not full_text.strip():
            continue

        results.append({
            'url': '',
            'title': _clean(row.get('Title')),
            'institution': _clean(row.get('Institution name')),
            'uoa': _clean(row.get('Unit of assessment name')),
            'rating': '',
            'full_text': full_text,
            'sections': sections,
            'researcher_orcids': _clean(row.get('Researcher ORCIDs')),
        })

    logger.info(f"  Found {len(results)} case studies for {university}")
    return results
