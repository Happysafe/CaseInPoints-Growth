"""
One-shot script: patches all existing Notion CRM pages with University Category
and the Change in 4* / Change in 3*+ deltas, derived from REF 2014 vs 2021
university-wide Impact sub-profiles.

Usage: python3 push_categories_to_notion.py [--dry-run]
"""
from __future__ import annotations

import logging

from pipeline.notion_backfill import run_backfill
from pipeline.notion_push import _select_prop, _number_prop, pp_to_percent
from pipeline.university_category import categorise_leads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("push_categories")


def _build_props(lead: dict) -> dict:
    return {
        "University Category": _select_prop(lead.get("university_category")),
        "Change in 4*": _number_prop(pp_to_percent(lead.get("change_in_4star"))),
        "Change in 3*+": _number_prop(pp_to_percent(lead.get("change_in_3star_plus"))),
    }


def _format_line(lead: dict) -> str:
    return f"{lead.get('contact_name', '?')} — {lead.get('university_category') or '—'}"


def _print_summary(leads: list[dict]) -> None:
    """Per-university category table for eyeballing before/after the push."""
    seen: dict[str, dict] = {}
    for lead in leads:
        uni = lead.get("university", "?")
        if uni not in seen:
            seen[uni] = lead

    print(f"\n{'University':<34} {'Category':<10} {'Δ4*':>7} {'Δ3*+':>7}")
    print("-" * 62)
    for uni in sorted(seen):
        lead = seen[uni]
        cat = lead.get("university_category") or "—"
        d4 = lead.get("change_in_4star")
        d3 = lead.get("change_in_3star_plus")
        d4s = f"{d4:+.1f}" if d4 is not None else "  n/a"
        d3s = f"{d3:+.1f}" if d3 is not None else "  n/a"
        print(f"{uni:<34} {cat:<10} {d4s:>7} {d3s:>7}")
    print()


def main():
    run_backfill(
        description="Push university categories to Notion CRM",
        schema_note="University Category and Change in 4*/3*+ columns",
        compute=lambda leads: categorise_leads(leads),
        pre_push=_print_summary,
        build_props=_build_props,
        format_line=_format_line,
        logger=logger,
    )


if __name__ == "__main__":
    main()
