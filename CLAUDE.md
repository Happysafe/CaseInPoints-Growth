# CaseInPoints Growth — REF Impact Intelligence System

## Project Overview

A B2B lead intelligence and sales pipeline targeting UK university professors and research offices preparing for REF 2029. The system ingests REF 2014 & 2021 public results data, infers each lead's Unit of Assessment, enriches professor profiles, and pushes university-level REF Impact performance to a Notion CRM.

**Product site:** https://2029.ref.ac.uk  
**Market:** ~50–80 decision-makers across UK HEIs (boutique, high-trust — quality over volume)

---

## System Architecture

```
Layer 1: Lead Intelligence     → Python pipeline (COMPLETE)
Layer 2: CRM                   → Notion database (COMPLETE — 70 lead pages live)
Layer 3: Outreach Sequence     → Claude-drafted emails (BUILT — generator done; no emails sent yet)
Layer 4: Trial Activation      → Calendly + Loom (NOT STARTED)
Layer 5: Post-Trial Conversion → Claude diagnostic reports (NOT STARTED)
```

---

## Always Do First
**Ask me clarifying questions** one at a time until you are 95% confident you can complete the tasks successfully.
**Invoke the "frontend-design" skill** before writing any front-end code, every session, no exceptions.
**Invoke the "code-simplifier" agent** whenever the user asks to clean up, simplify, or refactor code.
**Invoke the "webapp-testing" skill** whenever testing web app functionality (Streamlit dashboard, social brainstorm app).

## Testing Rules
- Always write tests before or alongside new code (TDD preferred)
- Run the full test suite after any change
- Never mark a task complete if tests are failing
- Run [eslint/prettier/your linter] on all modified files

---

## Current State (as of June 2026)

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
| `pipeline/enricher.py` | ORCID + Semantic Scholar profile enrichment (professor-only) | Done |
| `pipeline/notion_push.py` | Creates/updates Notion CRM schema and pushes one page per lead | Done |

**Output files:**
- `output/leads_enriched.json` — full enriched dataset (71 leads)
- `output/leads_enriched.csv` — same, flat CSV for review
- `output/checkpoint.json` — processed lead IDs 1–71

**Key implementation details:**
- `ref_scraper.py` uses a locally cached bulk export (`data/ref2021_impact_all.xlsx`) — not live scraping
- `enricher.py` deliberately skips API calls for `role_type == 'admin'` contacts
- Semantic Scholar API key is set but unauthenticated access is used (key causes 403 — see comment in `enricher.py`)
- Pipeline is idempotent: run with `--resume` to skip already-completed leads
- **Per-lead Claude scoring removed (June 2026):** `pipeline/scorer.py` was deleted. The CRM now shows the **university × UoA** Impact distribution instead of a per-case-study Pre-Score. See "University-level fields" below.

---

## Notion CRM

- **Database:** "REF Lead Pipeline"
- **Credentials:** `NOTION_TOKEN` and `NOTION_DATABASE_ID` in `.env`
- Schema is auto-created/patched on first run via `setup_schema()` in `notion_push.py`
- 70 active lead pages, all at Stage = "Identified" (originally 71 leads / 72 pages; 2 pre-existing duplicate-title pages — Cliona Boyle, Professor Stephen Cushion — were archived 2026-06-14, so titles are now unique)
- Key fields populated: 2014 & 2021 Impact 4*/3*/2*/1*/Unclassified (university-wide distribution), Key Weakness, University Key Strength, Research Theme, Impact Summary, H-Index, Top Paper, ORCID ID

**Schema migration (`setup_schema`):** on first push it renames legacy columns and deletes dropped ones against the live DB before adding any missing columns. Current migrations (`_RENAMES` / `_DELETIONS` in `notion_push.py`): `REF Impact *` → `2021 Impact *` (values preserved); delete `Pre-Score`, `REF Overall GPA`, `REF Scope`. Idempotent — a no-op once applied.

**`--refresh-notion` updates in place (no duplicates).** `push_to_notion` only PATCHes when the lead carries a `notion_page_id`. `refresh_notion` backfills `notion_page_id` at the start of each run via `fetch_page_ids_by_name()` (matching on the `Name`/contact field) before pushing, and persists the ids back to `output/leads_enriched.json`. Caveat: duplicate page titles are ambiguous — the first page seen wins (logged as a warning); DB titles are currently unique. (History: a run on 2026-06-14, before this fix, created 57 duplicates which were archived.)

### University-level fields (live — June 2026)

Plan files: `/Users/user/.claude/plans/investigate-the-feasibility-of-zany-pixel.md` (original), `/Users/user/.claude/plans/swift-riding-phoenix.md` (Pre-Score → distribution change)

The CRM reflects **institution-level** REF Impact performance plus UoA-specific qualitative notes:

- **2021 Impact 4* / 3* / 2* / 1* / Unclassified** and **2014 Impact 4* / 3* / 2* / 1* / Unclassified** (number, percent) — the **university-wide** Impact sub-profile distribution (unweighted mean across all the institution's UoA submissions) for each REF exercise. Year-prefixed and computed identically for both years so 2014↔2021 is directly comparable. (These replace the per-lead Pre-Score, removed along with `scorer.py`.)
- **University Key Strength** (rich_text) — Claude-generated across all case studies that institution submitted in that UoA.
- **Key Weakness** (rich_text) — *repurposed*. Per (university × UoA), same source as Key Strength.

**Both years are university-wide for ALL leads (June 2026).** Originally 2021 was UoA-specific where a UoA could be inferred, with a university-wide fallback for the ~44 REF-office / cross-institutional leads (e.g. "REF Impact Manager"). When 2014 was added, we standardised on **university-wide for both years and all 71 leads** so the numbers are comparable — REF 2014 used 36 UoAs vs 2021's 34 with different numbering, so per-UoA cross-year comparison isn't reliable. The old `REF Scope` column was dropped as it is now uniformly university-wide. Distributions come from `get_university_profile(university, year)`; strength/weakness remain UoA-specific (Claude) and stay blank for leads with no inferred UoA.

**Data sources:** `data/ref2021_results_all.xlsx` (results2021.ref.ac.uk) and `data/ref2014_results_all.xlsx` (results.ref.ac.uk → Download all results). The two files differ in layout (2014: header row 7, lowercase `unclassified`); `ref_results_scraper.py` handles both via its `_YEARS` config and caches each to `data/ref<year>_results_profiles.json`.

**Institution matching:** `_match_institution` uses fuzzy similarity with a `_MATCH_THRESHOLD` (0.6), rejects ambiguous ties, and has an `_ALIASES` map for names that don't fuzzy-match the official REF name. NB the two files name institutions differently — e.g. 2021 lists `Imperial College of Science, Technology and Medicine` (needs the alias) while 2014 lists the plain `Imperial College London` (resolves by fuzzy). All 22 lead universities resolve correctly in both years. Add new awkward names to `_ALIASES` as the lead set grows.

### University trajectory category (live — June 2026)

Plan file: `/Users/user/.claude/plans/now-classify-universities-in-glittery-teapot.md`

Each university is bucketed into one of four **trajectory categories** (2014→2021) that drive outreach framing. Pushed to all 71 Notion pages via `push_categories_to_notion.py`; also wired into `_university_fields`/`_build_properties` so future `run.py` pushes set them automatically. Both one-shot backfills (`push_categories_to_notion.py`, `push_tiers_to_notion.py`) now share the load/schema/patch-loop/CLI scaffolding in `pipeline/notion_backfill.py` (`run_backfill`), supplying only their per-lead `compute`/`build_props`/`format_line` callbacks.

- **University Category** (select: Leaders / Improvers / Stagnant / At Risk), **Change in 4\*** and **Change in 3\*+** (number, percent) — new Notion fields.
- **Classified on the Overall sub-profile, NOT Impact.** REF 2021 impact scores are inflated sector-wide (most research-intensive universities clear 50% Impact 4\*), so Impact can't discriminate — a 50% rule made ~16/22 leads "Leaders" and flagged nobody "At Risk". Overall 4\* spreads ~21–67% and yields a real split (current: 7 Leaders / 11 Improvers / 2 Stagnant / 2 At Risk). The separate `Impact 4*` columns are unaffected.
- **Rules** (first match wins — strength dominates, then risk, then momentum; thresholds are named constants in `university_category.py`): **Leaders** `Overall 2021 4* ≥ 50`; **At Risk** `4* < 35 AND 2*+1*+uncl > 20`; **Improvers** `Δ4* ≥ +10pp`; **Stagnant** otherwise. Precedence means a weak-but-rising university (e.g. Plymouth, Δ4*=+11.9) is flagged **At Risk**, not Improver, so it gets the impact-development pitch.
- Per-university (aggregated across all UoAs), **orthogonal to `Outreach Tier`** (impact GPA, governs *when* to contact — see below). Category governs *how* to pitch.
- Tested: `tests/test_university_category.py` (stdlib `unittest`, no pytest dep — `python3 -m unittest tests.test_university_category`).

### Outreach tiers (live — June 2026)

`pipeline/tier_leads.py` assigns each lead an **Outreach Tier** (1/2/3) from its REF 2021 **impact** sub-profile GPA mean — Tier 1 (≤3.10) sent first as the test cohort, then Tier 2 (≤3.55), then Tier 3. Pushed via `push_tiers_to_notion.py` to the `Outreach Tier` (select) and `UoA Impact Mean` (number) columns; `generate_outreach.py` filters by tier.

- **Sourced from the cached results data, not a hand-maintained table.** `get_tier_for_lead` calls `get_profile(uni, uoa, 2021)` for UoA-known leads and falls back to `get_university_profile(uni, 2021)` (university-wide impact mean) for the ~44 REF-office / cross-institutional leads with no inferred UoA. (Earlier versions used a 21-row hardcoded `_RAW_SCORES` stub, which left 60/71 leads as `?`; that table is gone.)
- `?` (mean `None`) only when the institution can't be matched in the results data at all — currently none of the 22 lead universities. `UoA Impact Mean` holds a university-wide mean for no-UoA leads (same impact-GPA scale, broader basis).
- Tested: `tests/test_tier_leads.py` (`python3 -m unittest tests.test_tier_leads`).

New modules:
- `pipeline/ref_results_scraper.py` — year-aware quality-profile loader (`_YEARS` config); `get_profile(uni, uoa, year)` and `get_university_profile(uni, year, profile='impact')` (the `profile` arg selects the sub-profile to aggregate — `university_category.py` passes `'overall'`).
- `pipeline/university_aggregator.py` — Claude `claude-opus-4-7` aggregator, caches to `output/university_assessments.json`.
- `pipeline/university_category.py` — REF trajectory classifier (`classify_university`, `categorise_leads`); reads cached profiles only, no scraping.
- `pipeline/notion_backfill.py` — shared scaffolding (`run_backfill`, `patch_page`) for the one-shot `push_*_to_notion.py` scripts. Shared serialisers live in `notion_push.py` (`pp_to_percent` for pp→Notion-percent; `quality_mean` in `ref_results_scraper.py` for the REF GPA mean).

---

## Environment

```
ANTHROPIC_API_KEY=  (Claude API — used for university × UoA aggregation)
NOTION_TOKEN=       (Notion integration token)
NOTION_DATABASE_ID= (target database)
SEMANTIC_SCHOLAR_KEY= (set but not used — unauthenticated works fine for 71 leads)
```

Install: `pip install -r requirements.txt`
Run: `python run.py` (defaults to `Research Impact Market.xlsx`)

---

## Next Steps — Layers 3–5

### Layer 3 — Outreach Sequence (BUILT — generator done; no emails sent yet)

Generates a 3-touch personalised email sequence per lead from their enriched CRM data:

| Touch | Timing | Hook |
|-------|--------|------|
| Cold email | Day 0 | Reference their institution's REF Impact performance (e.g. 2014→2021 trend) and Key Weakness |
| Value drop | Day 5 | Attach a 1-page pre-analysis PDF of their 2021 submission |
| Trial invite | Day 10 | Free full analysis of their REF 2029 draft |

**Inputs per lead:** contact name, university, department, research theme, impact summary, key weakness, 2014 vs 2021 Impact 4* trend  
**Tone:** Professional, peer-level, specific. Not salesy. "We noticed something interesting."  
**No bulk sending** — human reviews and sends each email manually.

**What was built:**
- `pipeline/outreach.py` — `generate_outreach(lead, ...)` drafts all 3 touches with Claude `claude-opus-4-7` (static system prompt is prompt-cached). Writes `output/outreach/lead_{id}/touch_{1,2,3}.md`; partial output is cleaned up on failure. Optionally pushes drafts to Notion as sub-pages and advances Stage → "Contacted".
- `generate_outreach.py` — CLI orchestrator: `python generate_outreach.py [--tier 1|2|3] [--lead-id N] [--resume] [--dry-run] [--push-notion]`. Filters to `role_type == 'professor'`, assigns tiers via `tier_leads`, and checkpoints to `output/outreach_checkpoint.json`. Recommended order: `--dry-run` → single `--lead-id` live test → full `--tier 1` batch.

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
