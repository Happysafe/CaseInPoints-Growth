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
from pipeline.extractor import best_match_for_lead, extract_structured
from pipeline.scorer import score_case_study
from pipeline.enricher import enrich_lead
from pipeline.notion_push import push_to_notion

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


def load_checkpoint() -> set[int]:
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return set(json.load(f).get('completed_ids', []))
    return set()


def save_checkpoint(completed_ids: set[int]):
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({'completed_ids': sorted(completed_ids), 'last_updated': datetime.utcnow().isoformat()}, f)


def save_outputs(leads: list[dict]):
    OUTPUT_DIR.mkdir(exist_ok=True)
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


def process_lead(lead: dict, dry_run: bool = False) -> dict:
    name = lead['contact_name']
    university = lead['university']

    # Step 1 — Infer Unit of Assessment
    uoa_result = infer_uoa(lead['position'], university)
    lead.update({
        'uoa_code': uoa_result['uoa_code'],
        'uoa_name': uoa_result['uoa_name'],
        'uoa_confidence': uoa_result['confidence'],
        'uoa_matched_keywords': uoa_result['matched_keywords'],
    })
    logger.info(
        f"  UoA: {uoa_result['uoa_code'] or 'Unknown'} — {uoa_result['uoa_name']} "
        f"(confidence={uoa_result['confidence']})"
    )

    if dry_run:
        lead['pre_score_status'] = 'dry_run'
        return lead

    # Step 2 — Fetch REF 2021 case studies
    case_studies = []
    try:
        case_studies = fetch_case_studies(university, uoa_result['uoa_code'], uoa_result['uoa_name'])
        logger.info(f"  REF case studies found: {len(case_studies)}")
    except Exception as e:
        logger.warning(f"  REF scrape failed: {e}")

    lead['ref_case_study_count'] = len(case_studies)

    # Step 3 — Extract structured content from best matching case study
    matched_cs = best_match_for_lead(lead, case_studies)
    if matched_cs:
        extracted = extract_structured(matched_cs)
        lead.update(extracted)
        logger.info(f"  Extracted case study: '{matched_cs.get('title', '')[:60]}'")
    else:
        lead['pre_score_status'] = 'no_case_study_found'
        logger.info("  No case study matched — enrichment will proceed without REF text")

    # Step 4 — Score with Claude
    if lead.get('research_summary') or lead.get('impact_summary'):
        try:
            scores = score_case_study(lead)
            if scores:
                lead['scores'] = scores
                lead['pre_score'] = scores.get('overall_score')
                lead['predicted_rating'] = scores.get('predicted_rating')
                lead['key_weakness'] = scores.get('key_weakness')
                lead['key_strength'] = scores.get('key_strength')
                lead['pre_score_status'] = 'scored'
        except Exception as e:
            logger.warning(f"  Scoring failed: {e}")
            lead['pre_score_status'] = 'scoring_failed'
    else:
        lead['pre_score_status'] = 'no_case_study_found'

    # Step 5 — Profile enrichment (ORCID + Semantic Scholar)
    try:
        enrich_lead(lead)
    except Exception as e:
        logger.warning(f"  Profile enrichment failed: {e}")

    # Step 6 — Push to Notion
    try:
        notion_page_id = push_to_notion(lead)
        if notion_page_id:
            lead['notion_page_id'] = notion_page_id
    except Exception as e:
        logger.warning(f"  Notion push failed: {e}")

    return lead


def main():
    parser = argparse.ArgumentParser(description='REF Lead Intelligence Pipeline')
    parser.add_argument('--input', default=DEFAULT_INPUT, help='Path to input Excel file')
    parser.add_argument('--resume', action='store_true', help='Skip already-completed leads (uses checkpoint)')
    parser.add_argument('--dry-run', action='store_true', help='Ingest and UoA inference only — skip all API calls')
    args = parser.parse_args()

    input_path = args.input
    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)

    logger.info(f"Loading leads from: {input_path}")
    leads = load_leads(input_path)
    logger.info(f"Loaded {len(leads)} leads")

    completed_ids = load_checkpoint() if args.resume else set()
    if completed_ids:
        logger.info(f"Resuming — {len(completed_ids)} leads already completed, skipping them")

    enriched: list[dict] = []

    # Load any already-completed leads from previous run to merge into output
    if args.resume and ENRICHED_JSON.exists():
        with open(ENRICHED_JSON) as f:
            enriched = json.load(f)

    to_process = [l for l in leads if l['lead_id'] not in completed_ids]
    total_to_process = len(to_process)
    processed = 0

    for lead in to_process:
        lead_id = lead['lead_id']
        processed += 1
        print(f"\n[{processed}/{total_to_process}] {lead['contact_name']} — {lead['university']} ({lead['role_type']})")

        try:
            result = process_lead(lead, dry_run=args.dry_run)
            enriched.append(result)
            completed_ids.add(lead_id)
        except Exception as e:
            logger.error(f"FAILED lead {lead_id} ({lead['contact_name']}): {e}", exc_info=True)
            lead['error'] = str(e)
            lead['pre_score_status'] = 'pipeline_error'
            enriched.append(lead)
            completed_ids.add(lead_id)  # mark as done so we don't retry indefinitely

        # Save outputs and checkpoint after every lead
        save_outputs(enriched)
        save_checkpoint(completed_ids)

    print(f"\n{'='*60}")
    print(f"Pipeline complete.")
    print(f"  Leads processed: {processed}")
    print(f"  Leads skipped (checkpoint): {len(completed_ids) - processed}")
    print(f"  Output: {ENRICHED_JSON}")

    scored = sum(1 for l in enriched if l.get('pre_score_status') == 'scored')
    no_cs = sum(1 for l in enriched if l.get('pre_score_status') == 'no_case_study_found')
    errors = sum(1 for l in enriched if l.get('pre_score_status') == 'pipeline_error')
    print(f"  Scored: {scored} | No case study: {no_cs} | Errors: {errors}")


if __name__ == '__main__':
    main()
