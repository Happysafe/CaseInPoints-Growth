"""
REF Lead Intelligence Pipeline — Layer 1
Usage: python run.py [--input path/to/file.xlsx] [--resume] [--dry-run]
"""
import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from pipeline.ingest import load_leads
from pipeline.uoa_mapper import infer_uoa
from pipeline.ref_scraper import fetch_case_studies
from pipeline.ref_results_scraper import warm_cache as warm_results_cache
from pipeline.extractor import best_match_for_lead, extract_structured
from pipeline.enricher import enrich_lead
from pipeline.university_aggregator import aggregate_all
from pipeline.notion_push import push_to_notion, fetch_page_ids_by_name

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('run')

OUTPUT_DIR = Path('output')
ENRICHED_JSON = OUTPUT_DIR / 'leads_enriched.json'
ENRICHED_CSV = OUTPUT_DIR / 'leads_enriched.csv'
CHECKPOINT_FILE = OUTPUT_DIR / 'checkpoint.json'

DEFAULT_INPUT = 'Research Impact Market.xlsx'
SAVE_EVERY = 5  # flush outputs every N leads


def load_checkpoint() -> set[int]:
    try:
        with open(CHECKPOINT_FILE) as f:
            return set(json.load(f).get('completed_ids', []))
    except FileNotFoundError:
        return set()


def save_checkpoint(completed_ids: set[int]):
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({'completed_ids': sorted(completed_ids), 'last_updated': datetime.utcnow().isoformat()}, f)


def save_outputs(leads: list[dict]):
    with open(ENRICHED_JSON, 'w') as f:
        json.dump(leads, f, indent=2, ensure_ascii=False, default=str)

    if leads:
        fieldnames = list(leads[0].keys())
        with open(ENRICHED_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for lead in leads:
                flat = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in lead.items()}
                writer.writerow(flat)

    logger.info(f"Saved {len(leads)} leads → {ENRICHED_JSON} and {ENRICHED_CSV}")


def assign_uoa(lead: dict) -> dict:
    """Infer the lead's Unit of Assessment and write the uoa_* fields in place."""
    uoa_result = infer_uoa(lead['position'], lead['university'])
    lead.update({
        'uoa_code': uoa_result['uoa_code'],
        'uoa_name': uoa_result['uoa_name'],
        'uoa_confidence': uoa_result['confidence'],
        'uoa_matched_keywords': uoa_result['matched_keywords'],
    })
    return uoa_result


def process_lead(lead: dict, dry_run: bool = False) -> dict:
    university = lead['university']

    uoa_result = assign_uoa(lead)
    logger.info(
        f"  UoA: {uoa_result['uoa_code'] or 'Unknown'} — {uoa_result['uoa_name']} "
        f"(confidence={uoa_result['confidence']})"
    )

    if dry_run:
        return lead

    case_studies = []
    try:
        case_studies = fetch_case_studies(university, uoa_result['uoa_code'], uoa_result['uoa_name'])
        logger.info(f"  REF case studies found: {len(case_studies)}")
    except Exception as e:
        logger.warning(f"  REF scrape failed: {e}")

    lead['ref_case_study_count'] = len(case_studies)

    matched_cs = best_match_for_lead(lead, case_studies)
    if matched_cs:
        lead.update(extract_structured(matched_cs))
        logger.info(f"  Extracted case study: '{matched_cs.get('title', '')[:60]}'")
    else:
        logger.info("  No case study matched — enrichment will proceed without REF text")

    try:
        enrich_lead(lead)
    except Exception as e:
        logger.warning(f"  Profile enrichment failed: {e}")

    try:
        notion_page_id = push_to_notion(lead)
        if notion_page_id:
            lead['notion_page_id'] = notion_page_id
    except Exception as e:
        logger.warning(f"  Notion push failed: {e}")

    return lead


def refresh_notion():
    """
    Re-aggregate university-level fields and PATCH existing Notion pages
    using leads from output/leads_enriched.json. Does not re-run per-lead
    enrichment or scoring.
    """
    if not ENRICHED_JSON.exists():
        logger.error(f"No enriched leads file found at {ENRICHED_JSON}")
        sys.exit(1)

    with open(ENRICHED_JSON) as f:
        leads = json.load(f)
    logger.info(f"Loaded {len(leads)} enriched leads for refresh")

    logger.info("Warming REF 2021 quality profiles cache…")
    warm_results_cache()

    logger.info("Running university × UoA aggregation (Claude)…")
    aggregate_all(leads)

    # Backfill notion_page_id by matching contact name to existing pages, so we
    # UPDATE in place rather than creating duplicates (leads_enriched.json does
    # not persist page ids from the original push).
    token = os.getenv('NOTION_TOKEN', '')
    database_id = os.getenv('NOTION_DATABASE_ID', '')
    if token and database_id:
        name_to_id = fetch_page_ids_by_name(token, database_id)
        backfilled = 0
        for lead in leads:
            if not lead.get('notion_page_id'):
                page_id = name_to_id.get(lead.get('contact_name', ''))
                if page_id:
                    lead['notion_page_id'] = page_id
                    backfilled += 1
        unmatched = sum(1 for lead in leads if not lead.get('notion_page_id'))
        logger.info(f"Backfilled notion_page_id for {backfilled} leads; {unmatched} unmatched (will be created)")

    logger.info("Pushing university-level fields to Notion…")
    updated = 0
    for i, lead in enumerate(leads, 1):
        print(f"[{i}/{len(leads)}] {lead.get('contact_name', '?')} — {lead.get('university', '?')}")
        page_id = push_to_notion(lead)
        if page_id:
            lead['notion_page_id'] = page_id
            updated += 1

    save_outputs(leads)
    logger.info(f"Refresh complete: {updated}/{len(leads)} Notion pages updated")


def main():
    parser = argparse.ArgumentParser(description='REF Lead Intelligence Pipeline')
    parser.add_argument('--input', default=DEFAULT_INPUT, help='Path to input Excel file')
    parser.add_argument('--resume', action='store_true', help='Skip already-completed leads (uses checkpoint)')
    parser.add_argument('--dry-run', action='store_true', help='Ingest and UoA inference only — skip all API calls')
    parser.add_argument('--refresh-notion', action='store_true',
                        help='Skip per-lead processing. Re-aggregate university-level fields and update existing Notion pages from leads_enriched.json.')
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.refresh_notion:
        return refresh_notion()

    if not Path(args.input).exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    logger.info(f"Loading leads from: {args.input}")
    leads = load_leads(args.input)
    logger.info(f"Loaded {len(leads)} leads")

    # Infer UoA for every lead up front so the aggregation below has uoa_code to
    # group by. (process_lead re-runs this per lead; it's idempotent.)
    logger.info("Inferring Units of Assessment…")
    for lead in leads:
        assign_uoa(lead)

    logger.info("Warming REF 2021 quality profiles cache…")
    warm_results_cache()

    logger.info("Running university × UoA aggregation (Claude)…")
    aggregate_all(leads)

    completed_ids = load_checkpoint() if args.resume else set()
    if completed_ids:
        logger.info(f"Resuming — {len(completed_ids)} leads already completed, skipping them")

    enriched: list[dict] = []
    if args.resume and ENRICHED_JSON.exists():
        with open(ENRICHED_JSON) as f:
            enriched = json.load(f)

    to_process = [lead for lead in leads if lead['lead_id'] not in completed_ids]
    total = len(to_process)

    for i, lead in enumerate(to_process, 1):
        lead_id = lead['lead_id']
        print(f"\n[{i}/{total}] {lead['contact_name']} — {lead['university']} ({lead['role_type']})")

        try:
            result = process_lead(lead, dry_run=args.dry_run)
            enriched.append(result)
            completed_ids.add(lead_id)
        except Exception as e:
            logger.error(f"FAILED lead {lead_id} ({lead['contact_name']}): {e}", exc_info=True)
            lead['error'] = str(e)
            enriched.append(lead)
            completed_ids.add(lead_id)

        if i % SAVE_EVERY == 0 or i == total:
            save_outputs(enriched)
            save_checkpoint(completed_ids)

    print(f"\n{'='*60}")
    print(f"Pipeline complete.")
    print(f"  Leads processed: {len(to_process)}")
    print(f"  Leads skipped (checkpoint): {len(completed_ids) - len(to_process)}")
    print(f"  Output: {ENRICHED_JSON}")

    errors = sum(1 for lead in enriched if lead.get('error'))
    print(f"  Total in output: {len(enriched)} | Errors: {errors}")


if __name__ == '__main__':
    main()
