# Singlife x NTU Technical Handover Overview

## Purpose
This handover package supports transition from prototype experimentation into capability stabilization, internal documentation, and operational readiness planning.

It is written for both:
- Engineering teams who need implementation-level details
- Management stakeholders who need scope, risks, and transition clarity

## Scope Covered
- Architecture walkthrough
- Code structure and dependencies
- Local setup and run flow
- Rule logic and explanation flow
- Current limitations and enhancement opportunities
- Module ownership map (which Python file does what)

## Handover Files
- `handover/01_architecture_walkthrough.md`
- `handover/02_code_structure_and_dependencies.md`
- `handover/03_local_setup_and_run.md`
- `handover/04_rule_logic_and_explanation_flow.md`
- `handover/05_limitations_and_enhancements.md`
- `handover/06_module_ownership_map.md`

## Executive Snapshot
- The system is a hybrid AI ops assistant: deterministic rules engine + RAG + LLM explanation.
- Decision-critical logic is configuration-driven in `knowledge_base/sop_rules.json` and `knowledge_base/qa_scoring_rules.json`.
- Backend is Flask-based with SSE streaming endpoints; frontend is a single-page vanilla JS app.
- Local-only deployment is currently documented and implemented; no production deployment pipeline is present.
- Human-in-the-loop remains the final authority for operational decisions.


