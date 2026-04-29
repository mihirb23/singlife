# Student Handover Checklist

**Audience**: NTU student team
**Version**: 3.0 · 2026-04-28

---

## Checklist Structure

This checklist has two parts:

| Part | Content |
|---|---|
| **Part 1: Asset Inventory** | The specific code, documents, configuration, and external resources to be handed over (location + purpose) |
| **Part 2: Data Flow Diagram Walkthrough** | What must be explained in person on the handover day |

---

# Part 1: Asset Inventory (Specific Items to Hand Over)

---

## 1.1 Source Repository

| Item | Location | Notes |
|---|---|---|
| GitHub repository | https://github.com/mihirb23/singlife.git (remote: `origin`) | Main repository |
| Main branch | `main` | Active development branch. Other branches: `origin/experience`, `origin/feature/chat-local-attachments` |
| Local repository | `/Users/mihirbhupathiraju/singlife/` | Contains all current code including files not yet pushed |

---

## 1.2 Backend Code (Python)

| File | Lines | Purpose |
|---|---|---|
| `backend/app.py` | ~450 | Main Flask server. Registers all 14 routes (10 `/api/*` endpoints and 4 HTML pages). Handles file uploads up to 50 MB, SSE streaming, and basic request validation. |
| `backend/services/__init__.py` | 3 | Python package init file, no logic inside. |
| `backend/services/claude_service.py` | ~1,015 | The main AI orchestrator. Contains the `InsuranceAssistant` class which handles all four modes (chat, evaluate, email, QA). The call sequence is: load KB, call RAG, build prompt, call Anthropic API, stream SSE back. Also handles conversation context trimming and contains the email draft template logic. |
| `backend/services/rules_engine.py` | ~605 | Deterministic rule engine. Loads rules from `knowledge_base/sop_rules.json` at startup. No hardcoded thresholds at all, everything comes from the JSON. Evaluates each case step by step (steps 1A to 9A) and returns PASS, FAIL, or HUMAN-Review with a `step_id` for traceability. Supports three channels: QnB, EzSub, and Hardcopy. |
| `backend/services/rag_service.py` | ~668 | Vector store service. Indexes all files in `knowledge_base/` using ChromaDB and Sentence Transformers. Chunks text into 1,500-character pieces with 200-character overlap. Uses `chroma_db/index_manifest.json` to track which files have changed so it only re-indexes what is necessary. Returns top-k relevant chunks for each query. |
| `backend/services/privacy_filter.py` | ~200 | PII masking layer. Called before every LLM request for the Evaluate, Email, and QA modes. Masks NRIC, email, phone number, credit card numbers, names, and addresses. Keeps an internal mapping so the original values can be shown back to the ops staff in the UI. **Chat mode bypasses this module entirely.** |
| `backend/services/audit_log.py` | ~111 | Compliance audit trail. Appends one JSONL record per API request to `logs/audit_log.jsonl`. Each record includes: request ID, timestamp, mode, input reference, decision, rule version, SOP version, KB version, reasoning summary, and status. The endpoint can be protected with `AUDIT_API_KEY` in the `.env`. |

---

## 1.3 Frontend Code (HTML / JS / CSS)

| File | Purpose |
|---|---|
| `frontend/index.html` | Main SPA entry point. Dark-themed layout with a collapsible sidebar, chat area, and bottom input bar. Has four mode buttons: Chat, Evaluate, Draft Email, and QA Review. Loads `marked.js` for Markdown rendering and `xlsx.js` for Excel file parsing. |
| `frontend/js/app.js` | About 1,035 lines of vanilla JavaScript with no framework. Manages all conversation state in `localStorage`. Handles SSE streaming with a typing effect. File upload logic (max 5 files, 5 MB each). Switches between modes and renders Markdown plus code blocks. |
| `frontend/css/styles.css` | About 731 lines. Dark theme using CSS variables for colours, spacing, and typography. Flexbox layout with a 260-px sidebar. Includes responsive breakpoints for mobile. |
| `frontend/architecture.html` | About 288 lines. An in-app documentation page showing the system architecture flow from Input through Privacy Filter, Rules Engine, RAG, and LLM to Output. Includes a capability matrix. |
| `frontend/audit.html` | About 283 lines. An audit log viewer that reads `logs/audit_log.jsonl` via `/api/audit-log`. Allows filtering by mode and date, exporting to CSV, and shows summary stat cards. |

---

## 1.4 Knowledge Base and Rules

### 1.4.1 Business Rule Sources (Dual-Source Structure)

| Source | Location | Maintainer |
|---|---|---|
| **Excel authoritative source** | Not committed to the repository. Maintained offline by the Singlife NBIG business team. The diagram refers to it as `LTC QnB Processing Rules.xlsx`. The project root also contains `NB.MASTER (MPCI Master File).xlsx` (83 MB, master case database). Confirm the exact file with the business owner on handover day. | Singlife NBIG / UW business team |
| **JSON derived source (loaded by system)** | `knowledge_base/sop_rules.json` (13 KB). This is what `rules_engine.py` loads at startup. It contains all evaluation steps (1A to 9A), channel gating rules, thresholds, and recommended actions. Also `knowledge_base/qa_scoring_rules.json` (3 KB) for the QA complexity scoring model. | Student team (must manually sync with Excel when rules change) |

**Clarify at handover:**
- Is the current JSON aligned with the latest Excel version?
- Is there a sync script or is it purely manual?

### 1.4.2 Reference Documents

| File | Purpose |
|---|---|
| `knowledge_base/sop_nbig_stp_001.txt` | Main SOP document: "New Business Pre-Issue Checks and Decisioning" (~445 lines) |
| `knowledge_base/sop_jet_uw_criteria.txt` | Underwriting criteria and decision thresholds |
| `knowledge_base/ref_email_communication_rules.txt` | Email generation and communication rules, used by the email mode |
| `knowledge_base/ref_email_triage_rules.txt` | Email routing and triage logic |
| `knowledge_base/ref_qa_underwriting_rules.txt` | QA underwriting assessment rules |
| `knowledge_base/ref_careshield_product.txt` | CareShield product details and coverage information |
| `knowledge_base/ref_l400_column_mapping.txt` | Mapping of L400 system columns to normalised case data fields |
| `knowledge_base/ref_icd_codes.txt` | ICD medical code reference database |
| `knowledge_base/ref_followup_codes_official.txt` | Official follow-up codes (latest version) |
| `knowledge_base/ref_*.txt` (14 more files) | Other reference data covering premiums, race update rules, MyInfo consent, NRIC search, field validation, and more |
| `knowledge_base/issues_and_gaps_log.txt` | Known issues and KB gaps logged during development |

---

## 1.5 Test Assets

| Item | Location | Notes |
|---|---|---|
| Test case scenarios | `knowledge_base/test_cases_qnb_ezsub.csv` | Four scenarios: TC-01 Happy Path, TC-02 Missing MyInfo, TC-03 Invalid Consent, TC-04 Multiple Clients. Includes expected decisions and reasons. |
| Expected outputs | `knowledge_base/test_cases_expected_output.csv` | Expected decision, automation trigger, outstanding follow-ups, and failed steps per test case (e.g. TC-09 expects "StandardWithFurtherRequirements"). |
| Mock case data | `Use case 2 (with mock up data).xlsx` (50 MB, project root) | Mock underwriting scenarios for manual end-to-end testing. |
| Master case database | `NB.MASTER (MPCI Master File).xlsx` (83 MB, project root) | Real master case file. Handle as sensitive data and do not commit to GitHub. |
| Manual test questions | `docs/test_questions.md` | Sample prompts for evaluating system responses across all modes. |

---

## 1.6 Runtime Data

### `.env` Variable Inventory (explain the meaning of each variable)

**Location**: `backend/.env`

| Variable | Example Value | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-api03-...` | API key for calling the Anthropic Claude API. Keep this secret and never commit it to Git. Rotate it immediately if it leaks. |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | The Claude model used for all LLM calls. Changing this affects cost, speed, and output quality. |
| `CLAUDE_MAX_TOKENS` | `8192` | Maximum number of tokens the LLM can generate per response. Controls output length and API cost. |
| `FLASK_ENV` | `development` | Flask run environment. Change to `production` before deploying. |
| `FLASK_DEBUG` | `false` | Enables Flask debug mode with auto-reload and verbose error pages. Must be `false` in production. |
| `PORT` | `5003` | Port the Flask server listens on. The frontend must point to the same port. |
| `ALLOWED_ORIGINS` | `http://localhost:5003,...` | **Dead configuration. This variable is not read by the current code.** In `app.py`, Flask-CORS is initialised with `CORS(app)` which is wide-open and ignores this setting. Proper CORS restrictions need to be set directly in `app.py` before production deployment. |
| `AUDIT_API_KEY` | *(empty in dev)* | Optional API key to restrict access to the `/api/audit-log` endpoint. If left empty, the endpoint is publicly accessible. |

---

# Part 2: Data Flow Diagram Walkthrough (Live Explanation on Handover Day)

You must explain: **module functions, data flow, data storage, risks, call sequence, code locations, and interactions with external systems.**

## 2.0 Reference Material

When presenting in person, open `docs/dataflow_diagram_EN.html` (the pre-drawn data flow diagram).

### Diagram Accuracy Note

The diagram is largely accurate and has been verified against the codebase. One discrepancy to flag on the day:

**`email_disclosure_renderer.py` does not exist as a standalone file.** The diagram shows "Email Renderer V3 (email_disclosure_renderer.py)" as a separate backend module, but this logic is actually inside `backend/services/claude_service.py`. There is no separate renderer file in `backend/services/`. Let the receiving team know so they are not confused when browsing the code.

All other components, routes, PII flow paths, and P0 risks shown in the diagram match the actual codebase.

## 2.1 Walk Through the 4 Zones of the Diagram

Walk through zones I, II, III, IV in order. For each zone, answer 3 questions: **What is it? What does it do? What are the risks?**

## 2.2 Walk Through the 5 Core Modules

### Module 1: PrivacyFilter (Partial Masking Layer)

**File**: `backend/services/privacy_filter.py` (~200 lines)

This module masks PII before anything gets sent to the LLM. It handles NRIC (partial masking), email (partial), phone (partial), name (replaced with a token like `[NAME_1]`), and addresses. It only runs for the Evaluate, Email, and QA modes. Chat mode bypasses it completely, which is a P0 risk (R-02). The masking is partial, meaning some identifying fragments like the NRIC tail, email domain, and phone prefix still leave the system.

### Module 2: Rules Engine (Deterministic Rule Engine)

**File**: `backend/services/rules_engine.py` (~605 lines)

This is the deterministic part of the system. It reads all its rules from `knowledge_base/sop_rules.json` at startup, so no rule logic is hardcoded in Python. Each case is evaluated step by step from 1A to 9A. Every result comes back with a `step_id` so the decision can be traced back to a specific rule. It supports three channels with different gating rules: QnB, EzSub, and Hardcopy.

### Module 3: RAG Service (Vector Retrieval)

**File**: `backend/services/rag_service.py` (~668 lines)

This service indexes all the knowledge base documents into a local ChromaDB vector store. The embedding model is `all-MiniLM-L6-v2` from HuggingFace, which runs locally on CPU with no network connection needed after the first download. Text is chunked into 1,500-character pieces. The manifest file tracks which documents have changed so re-indexing is incremental. For each query, it retrieves the top-k most relevant chunks and injects them into the system prompt.

### Module 4: Email Renderer (inside Claude Service)

**File**: `backend/services/claude_service.py` (the email prompt-building methods)

Note: The diagram labels this as `email_disclosure_renderer.py` but that file does not exist. The logic lives inside `claude_service.py`. It builds structured email drafts (Decline, Postpone, Counter-Offer) using deterministic Python templates before the LLM fills in the details. This approach bypasses RLHF refusal because the task is framed as template-filling rather than free generation of sensitive content.

### Module 5: Claude Service (Orchestrator)

**File**: `backend/services/claude_service.py` (~1,015 lines)

This is the central orchestrator. Every AI request flows through here. The sequence is: load KB context, call RAG for relevant chunks, build the prompt, call the Anthropic API, and stream the SSE response back. Each mode has its own independent `system_prompt`. This module also writes truncated Q&A records to `logs/qa_log.jsonl`. Chat-mode queries are written un-masked, which is a P0 risk (R-05).

---

## 2.3 End-to-End Field Trace (9 Steps)

Walk through one complete trace using real field values.

**Sample scenario**: Customer fills the form with NRIC = `S8483123I`, email = `john@x.com`, phone = `98765432`, and submits a Customer Postpone email request.

You must clearly state which PII **still appears** in the prompt that Anthropic receives.

| Step | What Happens | PII Status |
|---|---|---|
| 1 | User fills the form in the browser (`frontend/index.html` and `app.js`) | Raw PII held in memory and localStorage |
| 2 | Frontend POSTs the case JSON to `/api/generate-email` in `backend/app.py` | Raw PII in the HTTPS request body |
| 3 | `app.py` calls `PrivacyFilter.mask()` before passing data to Claude Service | NRIC becomes `S****123I`, name becomes `[NAME_1]`, email becomes `j***@x.com`, phone becomes `987***32` |
| 4 | `claude_service.py` calls `rag_service.get_relevant_context(query)` | Query uses masked data. ChromaDB contains only KB vectors and no customer PII. |
| 5 | RAG returns top-k KB chunks (email communication rules, SOP extracts) | No customer PII. KB contains business rules only. |
| 6 | `claude_service.py` builds the prompt with a system section (KB and rules) and a user section (masked case data) | Partially masked. NRIC tail `123I`, email domain `x.com`, phone fragments `987` and `32`, date of birth, medical diagnosis terms, and policy number are all still present. |
| 7 | Prompt is sent over HTTPS to Anthropic Claude API (US servers) | Cross-border data transfer with partially masked PII. This is P0 risk R-04. No DPA or ZDR is in place. |
| 8 | Anthropic streams SSE tokens back to `claude_service.py` then to `app.py` | AI-generated email draft |
| 9 | `app.py` streams the SSE response to the browser. `claude_service.py` appends a truncated entry to `logs/qa_log.jsonl`. | Output rendered to the user. Log entry written. For chat mode specifically, the query is written un-masked. |

**PII that still reaches Anthropic in the prompt**: NRIC first letter and last 4 characters (`S****123I`), email first character and full domain (`j***@x.com`), phone first 3 and last 2 digits (`987***32`), date of birth, sex, medical diagnosis terms (cancer type, BMI value, blood pressure), and policy number.

---

## Summary: On Handover Day You Only Need to Do Two Things

1. **Part 1**: Deliver every item in the asset inventory (repository, code, documents, KB, configuration)
2. **Part 2**: Walk through the data flow diagram in person

---

**Prepared by**: Singlife NTU student team
**Version**: 3.0
**Date**: 2026-04-28
