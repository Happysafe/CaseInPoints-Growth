from __future__ import annotations

import re
import openpyxl


PROFESSOR_TITLES = re.compile(
    r'\b(professor|prof\.|dr\.|doctor|dr |researcher|lecturer|reader|fellow|chair|emeritus)\b',
    re.IGNORECASE
)

ADMIN_KEYWORDS = re.compile(
    r'\b(manager|officer|administrator|coordinator|director|head of|lead|advisor|adviser|executive|consultant|officer)\b',
    re.IGNORECASE
)


def _parse_role_type(position: str) -> str:
    pos = position.lower()
    if PROFESSOR_TITLES.search(pos):
        return "professor"
    if ADMIN_KEYWORDS.search(pos):
        return "admin"
    return "unknown"


_DEPT_NAMED = re.compile(
    r'\b(school of|department of|faculty of|college of|institute of|centre for|center for|'
    r'division of|group of|school$|college$|faculty$|business school|law school|'
    r'research office|edinburgh research)',
    re.IGNORECASE
)

_JOB_TITLE_STARTS = re.compile(
    r'^(professor|prof\.|dr\.|mr\.|mrs\.|ms\.|director|dean|head|manager|officer|'
    r'research|impact|pro-vice|vice|deputy|senior|strategic|faculty)',
    re.IGNORECASE
)


def _parse_department(position: str) -> str:
    """
    Extract department from position text.
    Tries to find a comma-separated segment that looks like an organisational unit,
    not a job title.
    """
    parts = [p.strip() for p in position.split(',')]

    # Prefer a segment that has a known institutional unit keyword
    for part in reversed(parts):
        if _DEPT_NAMED.search(part):
            return part

    # Fall back to any segment that doesn't look like a job title
    for part in reversed(parts):
        if not _JOB_TITLE_STARTS.match(part) and len(part) > 5:
            return part

    return position.strip()


def load_leads(xlsx_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb['UK universities']

    rows = list(ws.iter_rows(min_row=2, values_only=True))

    # Row index 0 is the header row (row 2 in spreadsheet)
    # Columns: (blank), No., University, Contact Person, Position, Email, LinkedIn, ...
    HEADER_ROW = rows[0]
    # Map column name to index
    col_map = {}
    for i, cell in enumerate(HEADER_ROW):
        if cell:
            col_map[cell.strip()] = i

    no_idx = col_map.get('No. ', col_map.get('No.', 1))
    uni_idx = col_map.get('University ', col_map.get('University', 2))
    name_idx = col_map.get('Contact Person ', col_map.get('Contact Person', 3))
    pos_idx = col_map.get('Position ', col_map.get('Position', 4))
    email_idx = col_map.get('Email ', col_map.get('Email', 5))
    linkedin_idx = col_map.get('LinkedIn', 6)

    leads = []
    for row in rows[1:]:
        if not any(v for v in row if v is not None):
            continue

        number = row[no_idx] if no_idx < len(row) else None
        university = (row[uni_idx] or '').strip() if uni_idx < len(row) else ''
        contact_name = (row[name_idx] or '').strip() if name_idx < len(row) else ''
        position = (row[pos_idx] or '').strip() if pos_idx < len(row) else ''
        email = (row[email_idx] or '').strip() if email_idx < len(row) else ''
        linkedin = (row[linkedin_idx] or '').strip() if linkedin_idx < len(row) else ''

        if not university or not contact_name:
            continue

        department = _parse_department(position)
        role_type = _parse_role_type(contact_name + ' ' + position)

        leads.append({
            'lead_id': int(number) if number else len(leads) + 1,
            'university': university,
            'contact_name': contact_name,
            'position': position,
            'department': department,
            'role_type': role_type,
            'email': email,
            'linkedin': linkedin,
            # Enrichment fields populated downstream
            'uoa_code': None,
            'uoa_name': None,
            'uoa_confidence': None,
            'ref_case_studies': [],
            'pre_score': None,
            'pre_score_status': 'pending',
            'scores': None,
            'key_weakness': None,
            'key_strength': None,
            'predicted_rating': None,
            'research_summary': None,
            'impact_summary': None,
            'orcid_id': None,
            'semantic_scholar_id': None,
            'h_index': None,
            'citation_count': None,
            'top_paper': None,
        })

    wb.close()
    return leads
