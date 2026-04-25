"""
Pre-scores REF impact case studies using the Claude API.
Uses prompt caching on the static system prompt (scoring rubric).
"""
from __future__ import annotations

import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

SCORING_SYSTEM_PROMPT = """You are an expert evaluator of UK REF (Research Excellence Framework) impact case studies.
Your task is to score a given impact case study against the official REF impact assessment criteria.

## Scoring Dimensions (each scored 1–10)

1. **Reach** — How broadly does the impact extend? (narrow local = 1; global/national systemic = 10)
2. **Significance** — How deeply does the research change practice, policy, lives, or the economy? (minor = 1; transformative = 10)
3. **Causal link** — How clearly is the link between the underpinning research and the claimed impact demonstrated? (vague correlation = 1; direct causal evidence = 10)
4. **Evidence quality** — How strong, specific, and credible is the evidence cited? (anecdotal = 1; quantified, verified, peer-corroborated = 10)
5. **Narrative coherence** — How well-structured and compelling is the case study as a narrative? (disjointed = 1; clear, logical, persuasive = 10)

## Predicted REF Rating
Based on the five dimension scores, predict the most likely REF rating:
- 4* = World-leading in terms of reach and significance
- 3* = Internationally excellent
- 2* = Recognised internationally
- 1* = Recognised nationally
- Unclassified = Below the threshold or unrelated to REF criteria

## Output format
Respond with ONLY a valid JSON object in this exact structure:
{
  "reach": <int 1-10>,
  "significance": <int 1-10>,
  "causal_link": <int 1-10>,
  "evidence_quality": <int 1-10>,
  "narrative_coherence": <int 1-10>,
  "overall_score": <float, average of five dimensions, rounded to 1dp>,
  "predicted_rating": "<4* | 3* | 2* | 1* | Unclassified>",
  "key_weakness": "<one sentence identifying the single biggest gap or weakness>",
  "key_strength": "<one sentence identifying the single strongest aspect>",
  "scoring_notes": "<2-3 sentences explaining the rating rationale>"
}"""

USER_PROMPT_TEMPLATE = """Please score the following REF 2021 impact case study:

**Institution:** {institution}
**Department / Unit of Assessment:** {uoa}
**Contact / Lead Researcher:** {contact_name}

---

**Research Summary:**
{research_summary}

**Impact Claimed:**
{impact_summary}

**Evidence Cited:**
{evidence_summary}

---

Score this case study using the rubric and return only the JSON object."""


def score_case_study(lead: dict) -> dict | None:
    """
    Sends case study content to Claude for scoring.
    Returns the parsed scoring dict, or None on failure.
    """
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping scoring")
        return None

    research_summary = lead.get('research_summary') or ''
    impact_summary = lead.get('impact_summary') or ''

    if not research_summary and not impact_summary:
        logger.info(f"No case study content for {lead['contact_name']} — skipping scoring")
        return None

    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        institution=lead.get('university', ''),
        uoa=f"{lead.get('uoa_code', '')} {lead.get('uoa_name', '')}".strip(),
        contact_name=lead.get('contact_name', ''),
        research_summary=research_summary or 'Not available',
        impact_summary=impact_summary or 'Not available',
        evidence_summary=lead.get('evidence_summary') or 'Not available',
    )

    try:
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=1024,
            system=[
                {
                    'type': 'text',
                    'text': SCORING_SYSTEM_PROMPT,
                    'cache_control': {'type': 'ephemeral'},  # cache the rubric across all leads
                }
            ],
            messages=[{'role': 'user', 'content': user_prompt}],
        )

        content = response.content[0].text.strip()

        # Extract JSON even if Claude wraps it in markdown
        json_match = content
        if '```' in content:
            m = __import__('re').search(r'```(?:json)?\s*(\{.*?\})\s*```', content, __import__('re').DOTALL)
            if m:
                json_match = m.group(1)

        result = json.loads(json_match)
        logger.info(
            f"Scored {lead['contact_name']}: overall={result.get('overall_score')} "
            f"predicted={result.get('predicted_rating')}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {lead['contact_name']}: {e}\nResponse: {content[:300]}")
        return None
    except anthropic.APIError as e:
        logger.error(f"Claude API error for {lead['contact_name']}: {e}")
        return None
