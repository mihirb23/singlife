# Rule Logic and Explanation Flow

## Executive Summary
Decision logic is split into two layers:
- Deterministic SOP execution from `knowledge_base/sop_rules.json`
- LLM explanation layer that translates deterministic outputs into operator-friendly reports

This architecture preserves traceability while keeping natural-language usability.

## Deterministic Rule Engine Flow
Implemented in `backend/services/rules_engine.py`:

1. Load and cache SOP rules (`load_rules()`).
2. Normalize heterogeneous input fields (`normalize_case()`).
3. Apply channel gating (`QnB`, `EzSub`, `Hardcopy`) from config.
4. Execute step rules via `RULE_EXECUTORS`:
   - `document_exists`
   - `consent_timestamp`
   - `client_search_nric`
   - `client_record_found`
   - `field_match`
   - `all_followups_resolved`
   - `threshold_check`
   - `uw_indicator`
   - `rcs_trigger`
5. Aggregate step outcomes and derive final decision (`derive_decision()`).

## Decision Derivation Model
- Decision priority and fail statuses come from `decision_logic` config.
- Priority order supports escalation (for example Refer UW before lower-severity outcomes).
- Automation trigger (`Yes/No`) is mapped by final decision type in config.
- Final output includes:
  - `overall_decision`
  - `ops_outcome`
  - `dotsphere_steps`
  - `automation_trigger`
  - `steps_failed`
  - `decision_reason`

## Explanation Flow (LLM Layer)
Implemented in `backend/services/claude_service.py`:

1. Run deterministic evaluation first (`evaluate_with_rules_engine`).
2. Apply privacy filter before LLM call.
3. Retrieve relevant SOP context via RAG.
4. Construct structured instruction prompt with:
   - Rules engine JSON output
   - SOP context header and excerpts
5. Stream response to frontend over SSE.
6. Log interaction metadata and previews.

## RAG Context Behavior
- Intent-aware retrieval supports:
  - explicit file resolution
  - expanded neighboring chunk retrieval
  - fallback to full-source load when retrieval quality is weak
- Retrieval metadata is included in logging for observability.

## QA Scoring Logic (Use Case 3)
- Deterministic complexity scoring is driven by `knowledge_base/qa_scoring_rules.json`.
- Includes configurable indicators, thresholds, and risk-level mapping.
- LLM explains score and risk drivers but does not override underwriting decisions.

## Governance Positioning
- Deterministic engine is source of truth for rule outcomes.
- LLM is explanation and communication layer, not decision authority.
- Human operators remain accountable for final operational action.
