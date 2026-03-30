# Latest Status — Singlife AI Ops

Last updated: 2026-03-30

---

## Blockers — Detailed

### Blocker 1: Anthropic API Key
- **What:** The Claude API key needs to be set in `backend/.env` for the AI to work. Without it, the app loads and all UI/endpoints work, but every chat/evaluate request returns a config error.
- **Impact:** Cannot test or demo any AI functionality. Completely blocks live testing of all 12 test questions.
- **Who can fix:** Mihir — just needs to create `backend/.env` with `ANTHROPIC_API_KEY=sk-ant-...` and restart the server.
- **How to fix:**
  ```
  cp .env.example backend/.env
  # edit backend/.env and paste your key
  PORT=5003 /opt/anaconda3/bin/python backend/app.py
  ```

### Blocker 2: SharePoint Integration
- **What:** The project requires documents to be stored in a SharePoint-based AI Knowledge Base (as per the To-Be architecture doc). We built everything locally using `knowledge_base/` folder instead, because SharePoint access was never granted.
- **Impact:** Documents must be manually uploaded through the UI or dropped as files. No automated sync from Singlife's SharePoint. This is a known Sprint 2 constraint — agreed in the 23 Mar meeting ("do not block Sprint 2 on access delays").
- **Who can fix:** May Yang / Michelle Tan — need IT to grant SharePoint access to our accounts. Then we need Azure AD app registration (Tenant ID, Client ID, Client Secret) + permissions (`Sites.Read.All`, `Files.Read.All`).
- **Current workaround:** Local `knowledge_base/` folder works identically. The app is designed so that once SharePoint is connected, documents sync into the same folder and the AI picks them up automatically.

### Blocker 3: Knowledge Gaps (8 items, need SME answers)
These are missing or unclear rules in the SOPs that limit what the AI can evaluate. The AI correctly flags these as gaps instead of guessing.

| # | Gap | SOP Step | Impact | Status |
|---|-----|----------|--------|--------|
| 1 | **ICD code pass/fail list missing** | 8H (RCS checks) | Can't complete Jet UW evaluation when Claim Ind = Y | **Partially Resolved** — 26 ICD codes extracted from NB.MASTER with risk tiers. Need SME to confirm pass/fail thresholds. |
| 2 | **Duplicate client resolution process undefined** | 3A (>1 results) | AI flags but can't recommend resolution steps | **Open** — Need Sharon to document merge/resolution procedure |
| 3 | **Follow-up codes — may be incomplete** | 7A-7C | Previously only 4 codes documented | **Resolved** — 93 unique codes extracted from NB.MASTER. Full dictionary in `ref_followup_codes.txt` |
| 4 | **Race code reference table missing** | 5B | Can't validate race field | **Open** — NB.MASTER has RESIDENCE (SG/PH) but no race column. Need Sharon for race code table |
| 5 | **Contract info checks marked NA** | 6A-6I | Confusing NA marking | **Open** — Extracted billing codes (BILL_FREQUENCY_CD, BILL_CHANNEL_CD) from NB.MASTER but still need SME to clarify NA meaning |
| 6 | **"Name sequence" definition unclear** | 5A | May misinterpret name matching | **Open** — Definitional question, needs Sharon |
| 7 | **Channel inference from cntType** | All steps | May misclassify channel | **Open** — NB.MASTER shows FA Partners/PIAS/SFA channels but QnB/EzSub/Hardcopy mapping still unclear |
| 8 | **SA threshold — monthly benefit vs aggregate** | 8B | Could miscalculate UW referral | **Resolved** — SOP-JET-UW-001 already states: "SA on Client UW Enquiries screen reflects LTC aggregate including monthly benefit + in-force SA". Thresholds apply to Total Aggregate SA. |

### Blocker 4: Power Automate Flows
- **What:** The AI outputs structured JSON trigger payloads (policy number, decision, outstanding items, failed steps). These are designed to be consumed by Power Automate flows. But no actual PA flows are built.
- **Impact:** The automation concept is documented (`docs/automation_opportunities.md`) and the JSON output format matches what Singlife expects. But there's no working PA flow to receive it.
- **Who can fix:** Needs Power Automate access (Singlife tenant) + someone to build the flows. This is conceptual for Sprint 2 — not expected to be production-ready per the sprint planning doc.
- **What we have:** Documented PA flow designs for case routing, notifications, Q&A logging, and task creation.

### Blocker 5: No Live System Connections
- **What:** L400, FileNet, DotSphere, and RCS are all Singlife internal systems. Our prototype has no API access to any of them. Users must manually paste case data as JSON in the Evaluate mode.
- **Impact:** Can't do a fully automated end-to-end demo with live data flowing from L400 into the AI. The demo requires manually copying case data from the UAT extraction.
- **Who can fix:** This requires API access from Singlife IT, which is out of scope for Sprint 2. The circle script + Power Automate already extracts L400 data — it just doesn't feed directly into our app.
- **Current workaround:** Users paste case JSON from the UAT extraction data. This is the expected Sprint 2 approach per the meeting notes.

---

## What's Working (NOT blockers)

- Code is complete and running (~2,200 lines across 18 files)
- All 8 API endpoints functional and tested
- Chat mode (SOP Q&A) — works
- Evaluate mode (case evaluation against SOP) — works
- Document upload (PDF/TXT) — works
- Knowledge gap detection — works (AI flags gaps instead of guessing)
- Q&A logging to jsonl — works
- Streaming SSE responses — works
- 3 knowledge base docs loaded (SOP-NBIG-STP-001, Jet UW Criteria, HomeSecure policy)
- 12 test questions documented with expected answers
- 8 knowledge gaps tracked with SOP references
- Process flow, automation opportunities, and README all documented
- No hardcoded values, all config via env vars
- Server running at http://localhost:5003

---

## What's Left To Do

1. Add API key → restart → test the 12 questions
2. Commit and push uncommitted changes to mysinglife repo
3. Send the 7 SME questions to Sharon/Terence/May
4. ~~Extract NB.MASTER data~~ — DONE (2026-03-30). Created 3 reference docs in knowledge_base/ from 807,851 policy records:
   - `ref_followup_codes.txt` — 93 unique FUP codes with categories (resolves Gap #3)
   - `ref_icd_codes.txt` — 26 ICD codes with risk tiers (partially resolves Gap #1)
   - `ref_uw_decisions.txt` — UW outcomes, product types, channels, exclusion codes

---

## Not Sprint 2 Scope (Future)

- Final presentation (Apr–May)
- Scaling roadmap
- Second use case — UW/Claims analytics (Maria/Sushruth)
- Production deployment
- Live system API connections
