"""
REF Outreach Sequence Generator — Layer 3
Generates 3-touch personalised email drafts per professor lead.

Usage:
  python generate_outreach.py [--tier 1|2|3] [--resume] [--dry-run] [--lead-id N] [--push-notion]

Recommended run order:
  1. python generate_outreach.py --tier 1 --dry-run       # review prompts, no cost
  2. python generate_outreach.py --tier 1 --lead-id N     # single live test (~$0.15)
  3. python generate_outreach.py --tier 1                 # full Tier 1 batch (~$0.75)
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from pipeline.tier_leads import tier_leads
from pipeline.outreach import generate_outreach

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("generate_outreach")

OUTPUT_DIR = Path("output")
OUTREACH_DIR = OUTPUT_DIR / "outreach"
CHECKPOINT_FILE = OUTPUT_DIR / "outreach_checkpoint.json"
ENRICHED_JSON = OUTPUT_DIR / "leads_enriched.json"


def load_checkpoint() -> set[int]:
    try:
        with open(CHECKPOINT_FILE) as f:
            return set(json.load(f).get("completed_ids", []))
    except FileNotFoundError:
        return set()


def save_checkpoint(completed_ids: set[int]):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(
            {"completed_ids": sorted(completed_ids), "last_updated": datetime.utcnow().isoformat()},
            f,
        )


def is_already_generated(lead_id: int) -> bool:
    lead_dir = OUTREACH_DIR / f"lead_{lead_id}"
    if not lead_dir.exists():
        return False
    md_files = list(lead_dir.glob("touch_*.md"))
    return len(md_files) == 3


def main():
    parser = argparse.ArgumentParser(description="REF Outreach Sequence Generator — Layer 3")
    parser.add_argument("--tier", choices=["1", "2", "3"], default=None,
                        help="Only process leads of this tier (recommended: start with 1)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip leads already in outreach_checkpoint.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts only — no API calls, no file writes")
    parser.add_argument("--lead-id", type=int, default=None,
                        help="Process a single lead by ID (bypasses checkpoint, for testing)")
    parser.add_argument("--push-notion", action="store_true",
                        help="Push email drafts to Notion as sub-pages under each lead record")
    args = parser.parse_args()

    # Pre-flight: Notion token check
    notion_token = os.getenv("NOTION_TOKEN")
    if args.push_notion and not notion_token:
        logger.error("--push-notion requires NOTION_TOKEN to be set in .env")
        sys.exit(1)

    # Load leads
    if not ENRICHED_JSON.exists():
        logger.error("Leads file not found: %s — run run.py first", ENRICHED_JSON)
        sys.exit(1)

    with open(ENRICHED_JSON) as f:
        leads = json.load(f)
    logger.info("Loaded %d leads from %s", len(leads), ENRICHED_JSON)

    # Assign tiers
    leads = tier_leads(leads)

    # Filter to professors only (same pattern as enricher.py)
    professor_leads = [l for l in leads if l.get("role_type") == "professor"]
    logger.info("%d professor leads after role filter", len(professor_leads))

    # Warn about missing-tier leads
    unknown = [l for l in professor_leads if l.get("outreach_tier") == "?"]
    if unknown:
        print(f"\n⚠️  {len(unknown)} lead(s) have no REF impact data (tier='?') and will be skipped:")
        for l in unknown:
            print(f"   • {l.get('contact_name')} — {l.get('university')} (UoA {l.get('uoa_code')})")
        print("   Provide score distributions for these pairs and re-run to include them.\n")

    # Apply --lead-id filter
    if args.lead_id is not None:
        target = [l for l in professor_leads if l.get("lead_id") == args.lead_id]
        if not target:
            logger.error("Lead ID %d not found (or is not a professor lead)", args.lead_id)
            sys.exit(1)
        to_process = target
        use_checkpoint = False
    else:
        # Apply --tier filter
        if args.tier:
            professor_leads = [l for l in professor_leads if l.get("outreach_tier") == args.tier]
            logger.info("%d leads in Tier %s", len(professor_leads), args.tier)

        # Exclude unknown tier
        professor_leads = [l for l in professor_leads if l.get("outreach_tier") != "?"]

        # Apply --resume / file-existence skip
        completed_ids = load_checkpoint() if args.resume else set()
        to_process = [
            l for l in professor_leads
            if l["lead_id"] not in completed_ids and not is_already_generated(l["lead_id"])
        ]
        if args.resume:
            skipped = len(professor_leads) - len(to_process)
            if skipped:
                logger.info("Resuming — skipping %d already-generated lead(s)", skipped)
        use_checkpoint = True

    total = len(to_process)
    if total == 0:
        print("Nothing to process — all matching leads already generated. Use --resume to confirm.")
        sys.exit(0)

    OUTREACH_DIR.mkdir(parents=True, exist_ok=True)
    completed_ids = load_checkpoint() if use_checkpoint else set()

    succeeded = 0
    failed = 0

    for i, lead in enumerate(to_process, 1):
        lead_id = lead["lead_id"]
        tier = lead.get("outreach_tier", "?")
        mean = lead.get("uoa_mean_score", "N/A")
        print(
            f"\n[{i}/{total}] {lead.get('contact_name')} — {lead.get('university')} "
            f"(Tier {tier}, UoA mean {mean})"
        )

        ok = generate_outreach(
            lead=lead,
            output_dir=OUTREACH_DIR,
            dry_run=args.dry_run,
            push_notion=args.push_notion,
            notion_token=notion_token,
        )

        if ok:
            succeeded += 1
            if use_checkpoint and not args.dry_run:
                completed_ids.add(lead_id)
                save_checkpoint(completed_ids)
        else:
            failed += 1
            logger.warning("Skipping checkpoint update for failed lead %d", lead_id)

        # Courteous pause between leads (not between touches)
        if i < total and not args.dry_run:
            time.sleep(0.5)

    print(f"\n{'='*60}")
    print(f"Outreach generation complete.")
    print(f"  Processed: {total} | Succeeded: {succeeded} | Failed: {failed}")
    if not args.dry_run:
        print(f"  Drafts saved to: {OUTREACH_DIR}")
    if args.tier:
        remaining_tiers = [t for t in ("1", "2", "3") if t != args.tier]
        print(f"  Next: --tier {remaining_tiers[0]} after reviewing Tier {args.tier} replies.")


if __name__ == "__main__":
    main()
