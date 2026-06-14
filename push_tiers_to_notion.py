"""
One-shot script: patches all existing Notion CRM pages with Outreach Tier
and UoA Impact Mean values computed from REF 2021 impact sub-profile data.

Usage: python3 push_tiers_to_notion.py [--dry-run]
"""
from __future__ import annotations

import logging

from pipeline.notion_backfill import run_backfill
from pipeline.notion_push import _select_prop, _number_prop
from pipeline.tier_leads import tier_leads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("push_tiers")


def _build_props(lead: dict) -> dict:
    return {
        "Outreach Tier": _select_prop(lead.get("outreach_tier", "?")),
        "UoA Impact Mean": _number_prop(lead.get("uoa_mean_score")),
    }


def _format_line(lead: dict) -> str:
    name = lead.get("contact_name", "?")
    return f"{name} — Tier {lead.get('outreach_tier', '?')}, Mean {lead.get('uoa_mean_score')}"


def main():
    run_backfill(
        description="Push outreach tiers to Notion CRM",
        schema_note="Outreach Tier and UoA Impact Mean columns",
        compute=lambda leads: tier_leads(leads),
        build_props=_build_props,
        format_line=_format_line,
        logger=logger,
    )


if __name__ == "__main__":
    main()
