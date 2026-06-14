"""
Generates 3-touch personalised outreach email sequences for REF leads.
Uses Claude claude-opus-4-7 with prompt caching on the static system prompt.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import anthropic
import requests

from pipeline.notion_push import _headers, NOTION_BASE_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — must exceed 1,024 tokens to qualify for Anthropic cache.
# Includes full tone brief, 3-touch sequence guidance, REF 2029 context,
# and output format spec. Per-lead variable data goes in the user message.
# ---------------------------------------------------------------------------

OUTREACH_SYSTEM_PROMPT = """You are a specialist in REF (Research Excellence Framework) impact assessment, writing on behalf of CaseInPoints — a service that helps UK academics improve their REF 2029 impact case studies. CaseInPoints scores impact case studies against the five official REF dimensions: reach, significance, causal link, evidence quality, and narrative coherence. The service identifies the specific structural weaknesses in a professor's existing 2021 submission and shows them exactly what changes would lift their predicted rating for 2029.

## About REF 2029

REF 2029 (Research Excellence Framework) is the UK's system for assessing the quality of research in higher education institutions. Impact case studies — demonstrating real-world benefits of academic research — account for 25% of each institution's REF score. A single percentage-point improvement in impact rating translates directly into millions of pounds of QR (Quality-Related) research funding. UK universities submitted their REF 2021 case studies in 2021; results were published in 2022. REF 2029 submissions will open in 2027–2028. Academics who improve their case study quality now — when they still have time to gather new evidence and reshape the narrative — are best positioned to achieve 4* ratings.

## Tone and style rules

- Professional and peer-level. You are writing to a senior academic, not a prospect. Never use phrases like "I wanted to reach out", "I hope this finds you well", "I'm reaching out", "synergy", "game-changer", or any sales clichés.
- Specific to their actual work. The professor must feel you have genuinely read their submission — reference their institution, their research area, or a concrete observed weakness. Generic emails are worse than no email.
- Short: 150–200 words maximum for the body (excluding subject line and sign-off block). Every sentence must earn its place.
- Do not invent facts. Use only the data provided in the user message.
- Never mention numerical scores or predicted ratings in the email — this comes across as presumptuous.
- Sign off exactly as shown in the output format below.

## Three-touch sequence guidance

**Touch 1 — Cold (Day 0)**
Hook: The specific weakness identified in their REF 2021 submission. Frame it as a genuine observation, not a criticism — "We noticed that..." or "Something stood out when we read your 2021 submission...". The weakness is the reason you're writing; it signals that you've actually read their work. CTA: ask if they have 10 minutes to see what a 4* submission in their specific field looks like. Do not ask for a sale, a demo, or a meeting — the ask is minimal and framed as peer curiosity.

**Touch 2 — Value drop (Day 5)**
This is a follow-up assuming no reply to Touch 1. Hook: announce that you have prepared a 1-page pre-analysis of their 2021 submission. This pre-analysis covers: (1) how their submission scores against current REF 2029 criteria, (2) three specific improvements that would increase their predicted rating. Reference Touch 1 in one line maximum — do not re-explain it. CTA: reply to receive the pre-analysis. This is the lowest-friction ask in the sequence — just a reply.

**Touch 3 — Trial invite (Day 10)**
Final note in the sequence. Be transparent that this is the last message — no guilt, just honest. Hook: offer a free full analysis of their REF 2029 draft case study — the actual product trial. Frame urgency around the REF 2029 submission timeline (institutions are actively preparing now; the window to gather new impact evidence is narrowing), not around CaseInPoints. CTA: book a 20-minute call. Link placeholder: [CALENDLY_LINK].

## Output format

Return ONLY the following structure. No preamble, no explanation, no markdown heading:

**Subject:** <subject line — specific to their research area or institution, NOT generic like "REF 2029 preparation">

<email body — 150–200 words>

---
James Hartley
CaseInPoints
james@caseinpoints.com
https://2029.ref.ac.uk"""

# ---------------------------------------------------------------------------
# Per-touch user prompt templates
# ---------------------------------------------------------------------------

_TOUCH_1_TEMPLATE = """Draft Touch 1 (cold email, Day 0) for the following professor.

**Professor:** {contact_name}
**University:** {university}
**Department:** {department}
**Unit of Assessment:** {uoa_name}
**Case study title:** {case_study_title}
**REF 2021 actual rating:** {ref_2021_rating}

**Research background (from their 2021 submission):**
{research_summary}

**Impact claimed:**
{impact_summary}

**The specific weakness we identified in their submission:**
{key_weakness}

Instructions:
- Lead with the specific weakness as the hook — make it concrete, not generic.
- Do NOT mention a score or numerical rating.
- Subject line must reference their specific research area or institution — not just "REF 2029".
- CTA: ask if they have 10 minutes to see what a 4* submission in their field looks like."""

_TOUCH_2_TEMPLATE = """Draft Touch 2 (value drop follow-up, Day 5) for the same professor. They have not replied.

**Professor:** {contact_name}
**University:** {university}
**Case study title:** {case_study_title}

**Weakness identified in Touch 1:** {key_weakness}
**Key strength in their submission:** {key_strength}

Instructions:
- Reference Touch 1 in one line maximum — do not re-explain the weakness.
- Announce the 1-page pre-analysis we've prepared for them.
- CTA: reply to receive it. Keep the ask minimal.
- Subject line: can be a "Re:" forward-style or a new specific hook.
- 150 words maximum."""

_TOUCH_3_TEMPLATE = """Draft Touch 3 (trial invite, Day 10) for the same professor. Still no reply — this is the final message.

**Professor:** {contact_name}
**University:** {university}
**Department:** {department}
**Case study title:** {case_study_title}

**Weakness identified in earlier touches:** {key_weakness}

Instructions:
- Be transparent this is the final note — no guilt, just honest.
- Offer a free full analysis of their REF 2029 draft case study.
- Frame urgency around the REF 2029 timeline (preparing now = better outcomes), not around CaseInPoints.
- CTA: book a 20-minute call — use placeholder [CALENDLY_LINK].
- 150 words maximum."""

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_summary(text: str, max_chars: int = 400) -> str:
    """Strip REF PDF formatting artifacts and truncate."""
    if not text:
        return ""
    # Remove section headers like "### 2. Underpinning research (indicative maximum 500 words)"
    text = re.sub(r'###?\s*\d+\.\s*[^\n]+', '', text)
    # Remove escaped parens \( ... \)
    text = re.sub(r'\\\(.*?\\\)', '', text, flags=re.DOTALL)
    # Remove **bold** markers
    text = re.sub(r'\*\*.*?\*\*', '', text)
    # Collapse whitespace
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()[:max_chars]


def _clean_field(value, fallback: str = '') -> str:
    if value and str(value).strip():
        return str(value).strip()
    return fallback


def _build_user_prompt(touch: int, lead: dict) -> str:
    kwargs = dict(
        contact_name=_clean_field(lead.get("contact_name"), "Professor"),
        university=_clean_field(lead.get("university"), "your university"),
        department=_clean_field(lead.get("department"), "your department"),
        uoa_name=_clean_field(lead.get("uoa_name"), "your unit of assessment"),
        case_study_title=_clean_field(lead.get("case_study_title"), "your REF 2021 impact case study"),
        ref_2021_rating=_clean_field(lead.get("ref_2021_rating"), "Unknown"),
        research_summary=_clean_summary(lead.get("research_summary", ""), 400) or "Not available",
        impact_summary=_clean_summary(lead.get("impact_summary", ""), 400) or "Not available",
        key_weakness=_clean_field(
            lead.get("key_weakness"),
            "The case study would benefit from stronger evidence quality and a clearer "
            "causal link between the research and claimed impact.",
        ),
        key_strength=_clean_field(
            lead.get("key_strength"),
            "The underpinning research is well-described and credible.",
        ),
    )
    templates = {1: _TOUCH_1_TEMPLATE, 2: _TOUCH_2_TEMPLATE, 3: _TOUCH_3_TEMPLATE}
    return templates[touch].format(**kwargs)


def _call_claude(user_prompt: str) -> str | None:
    try:
        response = _get_client().messages.create(
            model="claude-opus-4-7",
            max_tokens=600,
            system=[
                {
                    "type": "text",
                    "text": OUTREACH_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = response.content[0].text.strip()
        if not content or "**Subject:**" not in content:
            logger.error("Claude response missing **Subject:** line: %s", content[:200])
            return None
        return content
    except anthropic.APIError as e:
        logger.error("Claude API error: %s", e)
        return None


def _write_touch_file(path: Path, touch: int, lead: dict, content: str):
    labels = {1: "Cold Email (Day 0)", 2: "Value Drop (Day 5)", 3: "Trial Invite (Day 10)"}
    header = (
        f"# Touch {touch} — {labels[touch]}\n"
        f"**Lead:** {lead.get('contact_name', '?')} — {lead.get('university', '?')}\n"
        f"**Tier:** {lead.get('outreach_tier', '?')}  |  "
        f"**UoA mean score:** {lead.get('uoa_mean_score', 'N/A')}\n"
        f"**Generated:** {datetime.utcnow().isoformat(timespec='seconds')}\n\n"
        f"---\n\n"
    )
    path.write_text(header + content + "\n", encoding="utf-8")


def _push_touch_to_notion(token: str, parent_page_id: str, touch: int, content: str) -> str | None:
    labels = {1: "Touch 1 — Cold Email (Day 0)", 2: "Touch 2 — Value Drop (Day 5)", 3: "Touch 3 — Trial Invite (Day 10)"}
    payload = {
        "parent": {"page_id": parent_page_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": labels[touch]}}]}
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
                },
            }
        ],
    }
    try:
        resp = requests.post(
            f"{NOTION_BASE_URL}/pages",
            headers=_headers(token),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        logger.error("Notion push failed for touch %d: %s", touch, e)
        return None


def _update_notion_stage(token: str, page_id: str, stage: str = "Contacted"):
    payload = {"properties": {"Stage": {"select": {"name": stage}}}}
    try:
        resp = requests.patch(
            f"{NOTION_BASE_URL}/pages/{page_id}",
            headers=_headers(token),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to update Notion Stage for page %s: %s", page_id, e)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_outreach(
    lead: dict,
    output_dir: Path,
    dry_run: bool = False,
    push_notion: bool = False,
    notion_token: str | None = None,
) -> bool:
    """
    Generates 3 email touches for a professor lead.

    Writes output_dir/lead_{id}/touch_1.md, touch_2.md, touch_3.md.
    Returns True on success, False on any failure (partial output is cleaned up).
    """
    lead_id = lead.get("lead_id")
    lead_dir = output_dir / f"lead_{lead_id}"

    if dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN — {lead.get('contact_name')} ({lead.get('university')})")
        print(f"  Tier: {lead.get('outreach_tier')} | UoA mean: {lead.get('uoa_mean_score')}")
        for touch in (1, 2, 3):
            prompt = _build_user_prompt(touch, lead)
            print(f"\n--- Touch {touch} user prompt ---\n{prompt}")
        print(f"\nDRY RUN: would write {lead_dir}/touch_1.md, touch_2.md, touch_3.md")
        return True

    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY not set")
        return False

    lead_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    try:
        for touch in (1, 2, 3):
            user_prompt = _build_user_prompt(touch, lead)
            content = _call_claude(user_prompt)
            if content is None:
                raise RuntimeError(f"Claude returned no content for touch {touch}")
            path = lead_dir / f"touch_{touch}.md"
            _write_touch_file(path, touch, lead, content)
            written.append(path)
            logger.info("  Touch %d written: %s", touch, path.name)

    except Exception as e:
        logger.error("Failed generating outreach for %s: %s", lead.get("contact_name"), e)
        # Clean up partial output
        if lead_dir.exists():
            shutil.rmtree(lead_dir)
        return False

    if push_notion and notion_token and lead.get("notion_page_id"):
        page_id = lead["notion_page_id"]
        all_pushed = True
        for touch in (1, 2, 3):
            content = (lead_dir / f"touch_{touch}.md").read_text(encoding="utf-8")
            child_id = _push_touch_to_notion(notion_token, page_id, touch, content)
            if child_id is None:
                all_pushed = False
        if all_pushed:
            _update_notion_stage(notion_token, page_id)

    return True
