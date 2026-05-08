# Module Ownership Map (Python File Responsibilities)

## Executive Summary
This map defines ownership by module responsibility (not people). It is intended to speed up maintenance, debugging, and future transition work.

## Backend Entry Point
- `backend/app.py`
  - Flask application bootstrap
  - API route definitions and request validation
  - SSE response streaming wrappers
  - Upload/delete/list endpoint wiring
  - Auth checks for admin/audit-protected endpoints

## Service Modules
- `backend/services/claude_service.py`
  - Main orchestration service for all AI modes (chat, evaluate, email, QA)
  - Prompt composition and streaming to Anthropic SDK
  - Retrieval strategy selection and context assembly
  - Rules-engine delegation and QA logging

- `backend/services/rules_engine.py`
  - Deterministic SOP rule execution engine
  - Case data normalization across input formats
  - Step-level evaluator functions
  - Final decision derivation from configured decision logic

- `backend/services/rag_service.py`
  - Knowledge file extraction (`txt`, `pdf`, `xlsx`, `json`)
  - Chunking and embedding into ChromaDB
  - Manifest-driven incremental indexing
  - Retrieval, source resolution, and expanded context assembly

- `backend/services/privacy_filter.py`
  - PII detection and masking logic
  - Structured and free-text sanitization before LLM calls
  - Optional restoration mapping utilities

- `backend/services/audit_log.py`
  - JSONL audit entry creation
  - Version metadata capture from config/env
  - Audit retrieval with filters, pagination, and validation
  - Audit endpoint auth helper

- `backend/services/llm_debug_printer.py`
  - Debug instrumentation for LLM request/response timing and usage

- `backend/services/__init__.py`
  - Package marker/init for service module namespace

## Utility Script
- `scripts/add_policy.py`
  - CLI ingestion utility for extracting PDF text into `knowledge_base/`

## Configuration Assets Driving Python Behavior
- `knowledge_base/sop_rules.json`
  - SOP steps, channel gating, and decision mapping for rules engine
- `knowledge_base/qa_scoring_rules.json`
  - QA complexity scoring indicators, points, and risk thresholds

## Suggested Operational Ownership Buckets (Functional)
- **API and orchestration:** `app.py`, `claude_service.py`
- **Decision logic:** `rules_engine.py`, `sop_rules.json`
- **Knowledge retrieval/indexing:** `rag_service.py`, KB docs
- **Security/compliance controls:** `privacy_filter.py`, `audit_log.py`
- **Tooling/support scripts:** `scripts/add_policy.py`
