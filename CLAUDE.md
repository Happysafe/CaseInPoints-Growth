# CaseInPoints Growth — REF Impact Intelligence System

## Project Overview

A B2B lead intelligence and sales pipeline targeting UK university professors and research offices preparing for REF 2029. The system ingests REF 2021 public data, scores case studies with Claude AI, enriches professor profiles, and pushes to a Notion CRM.

**Product site:** https://2029.ref.ac.uk  
**Market:** ~50–80 decision-makers across UK HEIs (boutique, high-trust — quality over volume)

---

## System Architecture

```
Layer 1: Lead Intelligence     → Python pipeline (COMPLETE)
Layer 2: CRM                   → Notion database (COMPLETE — 71 leads live)
Layer 3: Outreach Sequence     → Claude-drafted emails (NOT STARTED)
Layer 4: Trial Activation      → Calendly + Loom (NOT STARTED)
Layer 5: Post-Trial Conversion → Claude diagnostic reports (NOT STARTED)
```

---

## Current State (as of April 2026)

### Layer 1 — Lead Intelligence Pipeline: COMPLETE

All 71 leads have been fully processed and pushed to Notion. See `output/checkpoint.json`.

**What was built:**

| File | Purpose | Status |
|------|---------|--------|
| `run.py` | Main orchestrator — `python run.py [--input] [--resume] [--dry-run]` | Done |
| `pipeline/ingest.py` | Loads leads from `Research Impact Market.xlsx` ("UK universities" sheet) | Done |
| `pipeline/uoa_mapper.py` | Keyword-based UoA inference from job titles | Done |
| `pipeline/ref_scraper.py` | Matches leads to `data/ref2021_impact_all.xlsx` local dataset | Done |
| `pipeline/extractor.py` | Pulls structured fields (research summary, impact, evidence) from case study sections | Done |
| `pipeline/scorer.py` | Claude `claude-sonnet-4-6` scoring on 5 dimensions (reach, significance, causal link, evidence quality, narrative coherence) — with prompt caching on rubric | Done |
| `pipeline/enricher.py` | ORCID + Semantic Scholar profile enrichment (professor-only) | Done |
| `pipeline/notion_push.py` | Creates/updates Notion CRM schema and pushes one page per lead | Done |

**Output files:**
- `output/leads_enriched.json` — full enriched dataset (71 leads)
- `output/leads_enriched.csv` — same, flat CSV for review
- `output/checkpoint.json` — processed lead IDs 1–71

**Key implementation details:**
- `ref_scraper.py` uses a locally cached bulk export (`data/ref2021_impact_all.xlsx`) — not live scraping
- `scorer.py` uses `cache_control: ephemeral` on the system prompt to cache the scoring rubric across all leads
- `enricher.py` deliberately skips API calls for `role_type == 'admin'` contacts
- Semantic Scholar API key is set but unauthenticated access is used (key causes 403 — see comment in `enricher.py`)
- Pipeline is idempotent: run with `--resume` to skip already-completed leads

---

## Notion CRM

- **Database:** "REF Lead Pipeline"
- **Credentials:** `NOTION_TOKEN` and `NOTION_DATABASE_ID` in `.env`
- Schema is auto-created/patched on first run via `setup_schema()` in `notion_push.py`
- 71 leads pushed with Stage = "Identified"
- Key fields populated: Pre-Score (1–10), Predicted Rating, Key Weakness, Research Theme, Impact Summary, H-Index, Top Paper, ORCID ID

---

## Environment

```
ANTHROPIC_API_KEY=  (Claude API — used for scoring)
NOTION_TOKEN=       (Notion integration token)
NOTION_DATABASE_ID= (target database)
SEMANTIC_SCHOLAR_KEY= (set but not used — unauthenticated works fine for 71 leads)
```

Install: `pip install -r requirements.txt`
Run: `python run.py` (defaults to `Research Impact Market.xlsx`)

---

## Next Steps — Layers 3–5

### Layer 3 — Outreach Sequence (build next)

Generate a 3-touch personalised email sequence per lead using their enriched CRM data:

| Touch | Timing | Hook |
|-------|--------|------|
| Cold email | Day 0 | Reference their specific REF 2021 weakness identified in pre-scoring |
| Value drop | Day 5 | Attach a 1-page pre-analysis PDF of their 2021 submission |
| Trial invite | Day 10 | Free full analysis of their REF 2029 draft |

**Inputs per lead:** contact name, university, department, research theme, impact summary, key weakness, pre-score vs 4* gap  
**Tone:** Professional, peer-level, specific. Not salesy. "We noticed something interesting."  
**No bulk sending** — human reviews and sends each email manually.

Suggested implementation:
- Script to generate 3 emails per lead using Claude (claude-opus-4-7 for quality)
- Save to `output/outreach/lead_{id}/` as markdown files
- Optionally push drafts to Notion as sub-pages under each lead record

### Layer 4 — Trial Activation

- Calendly link on positive reply (20-min onboarding call)
- Loom video walkthrough to send before call
- Live product demo on the call using their actual draft case study

### Layer 5 — Post-Trial Conversion

- Claude generates personalised diagnostic report post-trial
- Human sends with warm note + pricing proposal
- Frame: REF 2029 preparation windows are tightening

---

## Strategic Notes

- **Social proof compounds fast** in this small academic community — one testimonial from a known professor is high-leverage
- REF panel members are public — some professors on the list sit on panels and are ideal early advocates
- Pre-analysis PDF sent in Touch 2 is the **single highest-leverage asset** — it must be exceptional
- Post-REF 2029 revenue cliff risk — plan adjacent use cases: grant impact assessment, UKRI reporting
- Email discovery for missing contacts: Apollo.io or Hunter.io (manual enrichment step)
