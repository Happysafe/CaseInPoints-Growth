"""
Shared scaffolding for the one-shot Notion backfill scripts
(`push_tiers_to_notion.py`, `push_categories_to_notion.py`).

Both scripts: load `output/leads_enriched.json`, compute some derived fields,
ensure the Notion schema, then PATCH each lead's existing page. This module
factors out the identical loading / schema / patch-loop / CLI plumbing so each
script only supplies what's lead-specific (how to build the page properties and
the per-lead log line).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable

import requests
from dotenv import load_dotenv

from pipeline.notion_push import _headers, NOTION_BASE_URL, setup_schema

ENRICHED_JSON = Path("output/leads_enriched.json")

# Property builder: lead -> Notion `properties` dict for the PATCH.
PropsBuilder = Callable[[dict], dict]
# Per-lead progress line shown during the patch loop.
LineFormatter = Callable[[dict], str]


def patch_page(token: str, page_id: str, props: dict, logger: logging.Logger) -> bool:
    try:
        resp = requests.patch(
            f"{NOTION_BASE_URL}/pages/{page_id}",
            headers=_headers(token),
            json={"properties": props},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("PATCH failed for page %s: %s", page_id, e)
        return False


def run_backfill(
    *,
    description: str,
    schema_note: str,
    build_props: PropsBuilder,
    format_line: LineFormatter,
    compute: Callable[[list[dict]], None],
    logger: logging.Logger,
    pre_push: Callable[[list[dict]], None] | None = None,
) -> None:
    """
    Standard backfill flow shared by the push-* scripts.

    - `compute(leads)` mutates the loaded leads in place, adding derived fields.
    - `build_props(lead)` returns the Notion properties to PATCH for that lead.
    - `format_line(lead)` returns the per-lead progress line.
    - `pre_push(leads)` is an optional hook (e.g. printing a summary table)
      run after compute but before any API calls.
    """
    load_dotenv()

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be patched, no API calls")
    args = parser.parse_args()

    token = os.getenv("NOTION_TOKEN", "")
    database_id = os.getenv("NOTION_DATABASE_ID", "")

    if not args.dry_run and (not token or not database_id):
        logger.error("NOTION_TOKEN and NOTION_DATABASE_ID must be set in .env")
        sys.exit(1)

    if not ENRICHED_JSON.exists():
        logger.error("Leads file not found: %s", ENRICHED_JSON)
        sys.exit(1)

    with open(ENRICHED_JSON) as f:
        leads = json.load(f)

    compute(leads)

    if pre_push:
        pre_push(leads)

    if not args.dry_run:
        logger.info("Ensuring Notion schema has %s...", schema_note)
        setup_schema(token, database_id)

    patchable = [l for l in leads if l.get("notion_page_id")]
    missing_page = [l for l in leads if not l.get("notion_page_id")]
    if missing_page:
        logger.warning("%d lead(s) have no notion_page_id and will be skipped", len(missing_page))

    logger.info("Patching %d Notion pages...", len(patchable))

    succeeded = failed = 0
    for i, lead in enumerate(patchable, 1):
        print(f"[{i}/{len(patchable)}] {format_line(lead)}")
        if args.dry_run:
            print(f"  DRY RUN: would PATCH {lead['notion_page_id']} → {build_props(lead)}")
            succeeded += 1
            continue
        if patch_page(token, lead["notion_page_id"], build_props(lead), logger):
            succeeded += 1
        else:
            failed += 1
        if i % 10 == 0:
            time.sleep(0.3)  # stay well within Notion rate limits

    print(f"\n{'='*50}")
    print(f"Done. Patched: {succeeded} | Failed: {failed}")
    if failed:
        print("Re-run to retry failed pages.")
