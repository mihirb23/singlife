# Architecture Walkthrough

## Executive Summary
The platform is a local-first AI Operations Assistant for insurance workflows. It combines:
- Deterministic SOP rule evaluation for traceable decision logic
- Retrieval-augmented context from internal knowledge files
- LLM-generated explanations and user-facing guidance

This design separates "decision computation" from "decision explanation" to reduce hallucination risk in core operational checks.

## Technical Flow
1. User interacts via frontend (`frontend/index.html`, `frontend/js/app.js`).
2. Requests are sent to Flask backend (`backend/app.py`).
3. Depending on mode, backend routes to:
   - Chat (`/api/chat`)
   - Evaluate (`/api/evaluate`)
   - Email draft (`/api/generate-email`)
   - QA review (`/api/qa-review`)
4. Backend service layer (`backend/services/claude_service.py`) orchestrates:
   - Rules engine (`backend/services/rules_engine.py`) for deterministic checks
   - RAG retrieval (`backend/services/rag_service.py`) for knowledge grounding
   - Privacy filtering (`backend/services/privacy_filter.py`) before LLM calls
5. LLM output is streamed back to UI over SSE.
6. Logs are persisted for traceability:
   - Q&A logs: `logs/qa_log.jsonl`
   - Audit logs: `logs/audit_log.jsonl`

## Logical Components
- **Presentation layer**
  - Single-page web app with mode switching, uploads, streaming rendering, and export.
- **API layer**
  - Flask route handlers and request validation in `backend/app.py`.
- **Domain logic layer**
  - SOP deterministic evaluation and decision derivation in `rules_engine.py`.
- **Knowledge and retrieval layer**
  - ChromaDB + sentence-transformer embeddings with incremental indexing in `rag_service.py`.
- **Safety and compliance layer**
  - PII masking and audit logging in `privacy_filter.py` and `audit_log.py`.

## Data and Artifact Locations
- Knowledge sources: `knowledge_base/`
- Vector index + manifest: `chroma_db/`
- Runtime logs: `logs/`
- Local config: `backend/.env`

## Current Boundaries
- No direct writeback into enterprise systems (L400, DotSphere, FileNet).
- No live production integration in this repo.
- Human review remains final for high-impact decisions.
