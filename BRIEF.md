# REF Impact Intelligence System — Project Brief
> AI-First Lead Intelligence & Sales Pipeline for REF 2029

---

## Product Context

We are building a B2B SaaS tool that helps UK university professors and research offices evaluate and improve their REF (Research Excellence Framework) impact case studies ahead of REF 2029. High REF scores directly determine university funding (~£2 billion/year distributed across UK HEIs) and academic standing.

**Website:** https://2029.ref.ac.uk  
**REF 2021 public database:** https://results2021.ref.ac.uk

Our tool analyses submitted and draft impact case studies against REF scoring criteria and provides structured, actionable recommendations to improve ratings.

---

## Go-To-Market Context

- **Market size:** ~50–80 decision-makers across UK university departments — a small, tight-knit community
- **Key insight:** REF 2021 impact case studies are publicly available. Every professor's past submission can be read, scored, and used as a personalised outreach hook
- **Conversion rate and satisfaction are the only metrics that matter** — this is a boutique play, not volume
- **Target personas:** University professors (primary contact), Research office leads / REF managers (budget holder)
- **Timing:** Institutions are beginning REF 2029 prep now (SPRE submissions underway). Anxiety rises sharply post-2027

---

## Full System Architecture

```
Layer 1: Lead Intelligence     → Claude Code (build)
Layer 2: CRM                   → Notion (via API)
Layer 3: Outreach Sequence     → Claude Code (draft) + Human (review & send) + Gmail
Layer 4: Trial Activation      → Our product + Calendly + Loom
Layer 5: Post-Trial Conversion → Claude-drafted reports + Human send
```

---

## Layer 1 — Lead Intelligence Pipeline (BUILD THIS FIRST)

### Goal
Ingest a list of target universities and departments, fetch their REF 2021 publicly submitted impact case studies, extract structured data, pre-score them, and push enriched lead records to a Notion CRM database.

### Inputs
- A CSV or JSON file containing: `university_name`, `department`, `professor_name` (optional), `unit_of_assessment`
- REF 2021 public results database (https://results2021.ref.ac.uk)
- ORCID API (https://pub.orcid.org/v3.0) — for academic profile enrichment
- Semantic Scholar API (https://api.semanticscholar.org) — for publication context

### Outputs
- Enriched lead records pushed to a Notion database (see schema below)
- A local JSON/CSV backup of all enriched data
- Optional: per-lead pre-analysis summary (text file or Notion page)

### Processing Steps

1. **Fetch REF 2021 case studies**
   - Query the REF 2021 results database by institution + unit of assessment
   - Download or scrape the impact case study PDFs/text
   - Check terms of use before bulk downloading — parse HTML where possible as alternative

2. **Extract structured data from each case study**
   - Professor / lead researcher name
   - Institution and department
   - Unit of assessment (UoA)
   - Research summary (2–3 sentences)
   - Impact claim (what real-world change is claimed)
   - Evidence of impact cited
   - Star rating received (1*, 2*, 3*, 4* or unclassified)

3. **Pre-score each case study** against REF impact criteria:
   - Reach (breadth of impact)
   - Significance (depth of change caused)
   - Clarity of causal link between research and impact
   - Quality and specificity of evidence
   - Narrative coherence
   - Output: score out of 10 per dimension + overall predicted rating

4. **Enrich professor profiles**
   - Look up professor via ORCID API → get verified publication list, affiliation, research identifiers
   - Look up via Semantic Scholar API → get citation count, h-index, top papers, research themes
   - Merge into lead record

5. **Push to Notion CRM**
   - Create one Notion page per lead in the target database
   - Populate all fields per schema below

### Notion CRM Schema

```
Database name: "REF Lead Pipeline"

Fields:
- Name (title)                    → Professor full name
- University (text)               → Institution name
- Department (text)               → Department / school name
- Unit of Assessment (select)     → REF UoA code + name
- REF 2021 Rating (select)        → 4*, 3*, 2*, 1*, Unclassified, Unknown
- Pre-Score (number)              → Our predicted score 1–10
- Research Theme (text)           → 2–3 sentence summary of their research
- Impact Summary (text)           → What impact they claimed in REF 2021
- Key Weakness (text)             → Top gap identified in their case study
- Email (email)                   → Contact email (from Apollo/Hunter enrichment — manual input initially)
- LinkedIn (url)                  → LinkedIn profile URL
- ORCID ID (text)                 → ORCID identifier
- Semantic Scholar ID (text)      → SS author identifier
- H-Index (number)                → From Semantic Scholar
- Top Paper (text)                → Most cited paper title
- Stage (select)                  → Identified / Contacted / Engaged / Trial / Meeting / Closed / Dead
- Last Touch (date)               → Date of last outreach action
- Owner (person)                  → Team member responsible
- Notes (text)                    → Free-form notes
- Next Action (text)              → What happens next
- Pre-Analysis File (url)         → Link to pre-analysis doc (Notion page or Drive link)
- Calendly Link Sent (checkbox)   → Whether trial booking link was sent
- Trial Completed (checkbox)      → Whether trial session occurred
```

### Notion API Setup Required
- Create a Notion integration at https://www.notion.so/my-integrations
- Share the target database with the integration
- Store the integration token as `NOTION_TOKEN` in `.env`
- Store the target database ID as `NOTION_DATABASE_ID` in `.env`

---

## Layer 2 — CRM: Notion

Notion replaces Airtable. All lead records live in the "REF Lead Pipeline" database above.

Additional Notion pages to create in the same workspace:
- `Outreach Templates` — store the 3-touch email sequence per persona type
- `Call Notes` — one sub-page per lead, linked from their CRM record
- `Pre-Analysis Reports` — one sub-page per lead containing the full diagnostic

---

## Layer 3 — Outreach Sequence (Build After Layer 1)

### Email Logic
Claude Code drafts 3 emails per lead using their enriched CRM data. A human reviews and sends each email manually. No bulk sending — each email feels individually crafted.

### 3-Touch Sequence

| Touch | Timing | Goal | Key Hook |
|-------|--------|------|----------|
| Cold email | Day 0 | Create curiosity | Reference their specific REF 2021 case study + one structural weakness we identified |
| Value drop | Day 5 | Establish credibility | Attach a 1-page pre-analysis PDF of their 2021 submission |
| Trial invite | Day 10 | Invite to test | Offer a free full analysis of their REF 2029 draft |

### Email Drafting Inputs (per lead)
- Professor name, university, department
- Research theme summary
- Impact summary from their REF 2021 submission
- Key weakness identified in pre-scoring
- Our pre-score vs what a 4* submission would look like

### Tone
Professional, specific, peer-level. Not salesy. More like "we noticed something interesting about your impact submission and wanted to share it." Position as a specialist service, not software.

---

## Layer 4 — Trial Activation

- Calendly link sent on positive reply — 20-min onboarding call
- Loom video sent before call — walkthrough of tool analysing an anonymised real case study
- On call: run their actual draft case study live through the tool — let the product sell itself

---

## Layer 5 — Post-Trial Conversion

- After trial: Claude generates a personalised diagnostic report (scored, with specific recommendations)
- Human sends with a warm note and pricing proposal
- Light urgency frame: REF 2029 preparation windows are tightening — early movers build better case studies

---

## Technical Constraints & Notes

- **REF 2021 data:** Parse publicly available HTML pages where possible before attempting PDF bulk download. Check terms at https://2029.ref.ac.uk/terms-and-conditions/
- **APIs:** ORCID is free and open. Semantic Scholar is free with rate limits (~100 req/5min unauthenticated, 1 req/sec with API key)
- **Email contact discovery:** Apollo.io or Hunter.io for finding professor emails — this is done manually or as a separate enrichment step, not automated
- **Environment:** `.env` file for all secrets (NOTION_TOKEN, NOTION_DATABASE_ID, SEMANTIC_SCHOLAR_KEY, ORCID_CLIENT_ID)
- **Language preference:** Python preferred for data pipeline; Node.js acceptable for Notion API calls
- **Output format:** All data should also be saved locally as `leads_enriched.json` as a backup

---

## Immediate Build Priority

**Start with Layer 1.** Before writing any code, ask clarifying questions about:

1. Format and location of the input lead list (CSV? Manual entry? How many leads initially?)
2. Whether we have Notion API credentials already set up
3. Preferred approach for REF 2021 data: HTML scraping vs PDF download
4. Whether to use Claude API for pre-scoring or a simpler heuristic scoring model for v1
5. Rate limiting and error handling expectations

---

## Strategic Context (Do Not Skip)

- This is a **boutique, high-trust market** — every automated action must feel human and considered
- The pre-analysis sent in the cold email is the single highest-leverage asset in the pipeline
- **Social proof compounds fast** in a small academic community — one strong testimonial from a known professor unlocks many doors
- REF panel members are public — some professors sit on panels and are ideal early advocates
- Post-REF 2029 revenue cliff is a known risk — plan for adjacent use cases (grant impact assessment, UKRI reporting)

---

*Last updated: April 2026 | Owner: Helloworld | Status: Layer 1 build commencing*
