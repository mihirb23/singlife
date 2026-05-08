# Code Structure and Dependencies

## Executive Summary
The codebase is organized by clear concerns: frontend UI, Flask API, service modules, and knowledge/config assets. Core business behavior is largely configuration-driven through JSON rules files.

## Top-Level Structure
- `backend/`
  - `app.py`: Flask server, route definitions, endpoint-level validations, SSE streaming responses
  - `services/`: business and platform services (rules, RAG, privacy, audit, LLM orchestration)
- `frontend/`
  - `index.html`, `architecture.html`, `audit.html`
  - `js/app.js`: UI interactions, mode switching, SSE parsing, export logic
  - `css/styles.css`: app styling
- `knowledge_base/`
  - SOP and scoring rule configs (`sop_rules.json`, `qa_scoring_rules.json`) plus retrievable documents
- `scripts/`
  - `add_policy.py`: CLI utility for adding PDF policy text into KB
- `docs/`
  - Process and opportunity documentation

## Core Python Modules
- `backend/services/claude_service.py`
  - Central orchestration for chat/evaluate/email/qa flows
  - Retrieval strategy, prompt construction, streaming, QA logging
- `backend/services/rules_engine.py`
  - Deterministic SOP execution and final decision derivation
  - Rule executors mapped by rule type; mostly config-driven
- `backend/services/rag_service.py`
  - Document extraction, chunking, embedding, vector query, and manifest-based incremental indexing
- `backend/services/privacy_filter.py`
  - PII sanitization of LLM-bound content
- `backend/services/audit_log.py`
  - Immutable-style JSONL audit trail with filters/pagination support

## Main Runtime Dependencies
From `requirements.txt`:
- `flask`, `flask-cors`
- `anthropic`
- `python-dotenv`
- `pypdf`
- `openpyxl`
- `chromadb`
- `sentence-transformers`

## Config and Runtime Parameters
Common environment variables in `backend/.env`:
- `ANTHROPIC_API_KEY`
- `CLAUDE_MODEL`
- `CLAUDE_MAX_TOKENS`
- `PORT`, `FLASK_DEBUG`, `FLASK_HOST`
- `ADMIN_API_KEY`, `AUDIT_API_KEY`
- `ALLOWED_ORIGINS`

## Engineering Notes for Stabilization
- Rule behavior changes should prefer JSON config updates before Python logic changes.
- RAG behavior is stateful via `chroma_db/index_manifest.json`; keep this in operational runbooks.
- Logging and auth key behavior have explicit "dev mode if key missing" semantics that should be tightened for enterprise transition.
