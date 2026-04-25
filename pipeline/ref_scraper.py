"""
REF 2021 impact case study lookup — uses locally cached bulk export.
The full dataset is downloaded once to data/ref2021_impact_all.xlsx.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'ref2021_impact_all.xlsx')

_df = None  # module-level cache of the dataset


def _load_dataset():
    global _df
    if _df is not None:
        return _df

    try:
        import pandas as pd
        _df = pd.read_excel(DATA_PATH)
        logger.info(f"Loaded REF 2021 dataset: {len(_df)} case studies")
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

    # Exact or contains match
    if a == b or a in b or b in a:
        return 1.0

    # Word overlap
    a_words = set(re.findall(r'\b[a-z]{3,}\b', a))
    b_words = set(re.findall(r'\b[a-z]{3,}\b', b))
    # Remove common noise words
    stopwords = {'university', 'of', 'the', 'and', 'college', 'school'}
    a_words -= stopwords
    b_words -= stopwords

    if not a_words or not b_words:
        return 0.0

    overlap = len(a_words & b_words)
    return overlap / max(len(a_words), len(b_words))


def fetch_case_studies(university: str, uoa_code: str | None, uoa_name: str | None) -> list[dict]:
    """
    Return matching case studies from the local dataset for the given
    institution and (optionally) unit of assessment.
    Each returned dict has: title, institution, uoa, full_text, sections.
    """
    df = _load_dataset()
    if df is None:
        return []

    # Find best institution match
    unique_insts = df['Institution name'].dropna().unique()
    best_inst = None
    best_score = 0.0
    for inst in unique_insts:
        score = _institution_similarity(university, str(inst))
        if score > best_score:
            best_score = score
            best_inst = inst

    if best_inst is None or best_score < 0.3:
        logger.warning(f"No institution match for '{university}' (best score: {best_score:.2f})")
        return []

    logger.info(f"  Matched '{university}' → '{best_inst}' (score={best_score:.2f})")
    filtered = df[df['Institution name'] == best_inst]

    # Filter by UoA if we have one
    if uoa_code:
        uoa_num = uoa_code.replace('UoA ', '').strip()
        try:
            uoa_int = int(uoa_num)
            uoa_filtered = filtered[filtered['Unit of assessment number'] == uoa_int]
            if len(uoa_filtered) > 0:
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
        if len(name_filtered) > 0:
            filtered = name_filtered

    results = []
    for _, row in filtered.iterrows():
        sections = {
            'Summary of the impact': str(row.get('1. Summary of the impact') or ''),
            'Underpinning research': str(row.get('2. Underpinning research') or ''),
            'References to the research': str(row.get('3. References to the research') or ''),
            'Details of the impact': str(row.get('4. Details of the impact') or ''),
            'Sources to corroborate the impact': str(row.get('5. Sources to corroborate the impact') or ''),
        }
        # Strip nan
        sections = {k: (v if v != 'nan' else '') for k, v in sections.items()}

        full_text = '\n\n'.join(f"### {k}\n{v}" for k, v in sections.items() if v)

        if not full_text.strip():
            continue

        results.append({
            'url': '',
            'title': str(row.get('Title') or ''),
            'institution': str(row.get('Institution name') or ''),
            'uoa': str(row.get('Unit of assessment name') or ''),
            'rating': '',  # REF 2021 ratings not in this export
            'full_text': full_text,
            'sections': sections,
            'researcher_orcids': str(row.get('Researcher ORCIDs') or ''),
        })

    logger.info(f"  Found {len(results)} case studies for {university}")
    return results
