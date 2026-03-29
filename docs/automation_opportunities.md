# Automation & RPA Opportunities

Documents where AI outputs could trigger automated workflows,
and identifies candidate processes for future RPA development.

---

## Power Automate Integration Concept

### How it would work

The AI evaluation endpoint (`/api/evaluate`) already outputs structured JSON like:

```json
{
  "policyNumber": "G0406789",
  "decision": "StandardWithRequirements",
  "outstandingItems": ["Name mismatch", "CSL follow-up unresolved"],
  "sopStepsFailed": ["5C", "7B"],
  "recommendedAction": "Request updated client info, resolve CSL follow-up"
}
```

A Power Automate flow could consume this JSON to:

1. **Route the case** to the correct ops queue based on decision type
2. **Send notifications** (email/Teams) for outstanding items
3. **Update a SharePoint list** with the case status and AI recommendation
4. **Create tasks** in the team's task tracker for manual review items

### Proposed Flow: Submit Question → Get AI Answer (US3.2)

```
Trigger: User submits case data via Teams form / SharePoint form
    |
    v
Power Automate: HTTP POST to /api/evaluate with case data
    |
    v
Power Automate: Parse the SSE stream / collect response
    |
    v
Power Automate: Extract automation trigger JSON from response
    |
    v
Condition: decision type?
    |
    +-- Standard --> Update SharePoint list as "Approved"
    |                Send confirmation to ops staff
    |
    +-- StandardWithRequirements --> Create task for outstanding items
    |                                 Send email to ops staff with action items
    |
    +-- ReferToUW --> Route to UW team queue
    |                 Send Teams notification to UW team
    |
    +-- TriggerGNS --> Route to compliance team
    |
    +-- Withdrawal --> Update case status, notify relevant parties
```

### Proposed Flow: Q&A Logging (US3.3)

```
Trigger: Scheduled (daily/weekly)
    |
    v
Power Automate: HTTP GET /api/logs?limit=100
    |
    v
Power Automate: Parse log entries
    |
    v
Power Automate: Write to SharePoint list / Excel tracker
    |
    v
Power Automate: Flag entries where AI was uncertain
    |
    v
Power Automate: Send weekly summary to project sponsor
```

---

## RPA Opportunity Candidates (US3.4)

Processes where AI output could trigger automated actions in the future:

### High Priority (clear inputs, rule-based, repetitive)

| # | Process Step | Current State | RPA Opportunity | Required Inputs | Constraints |
|---|-------------|---------------|----------------|----------------|-------------|
| 1 | L400 data extraction | Power Automate + circle script pulls data | Already partially automated — could be extended to feed directly into AI evaluation | Contract number, client number | Needs L400 API access |
| 2 | Client field comparison (Step 5C) | Ops staff manually compares fields | RPA could auto-compare L400 vs application form fields and generate a mismatch report | L400 record, application form data | Read-only — cannot auto-update |
| 3 | Follow-up code status check (Step 7B) | Ops staff checks each FUP manually | RPA could scan all FUP codes and flag any non-R items | Contract number | Simple lookup — good RPA candidate |
| 4 | Jet UW indicator check (Steps 8B-8F) | Ops staff checks each indicator | RPA could evaluate all 5 indicators against threshold rules | Client UW enquiries data | Pure rule-based — ideal for RPA |

### Medium Priority (needs some judgment)

| # | Process Step | Current State | RPA Opportunity | Required Inputs | Constraints |
|---|-------------|---------------|----------------|----------------|-------------|
| 5 | Decision routing (Step 9A) | Ops staff selects decision in DotSphere | Could auto-select decision based on AI recommendation (with human approval) | AI decision output | Needs human confirmation step |
| 6 | Acceptance letter printing | Manual step after Standard decision | Could auto-trigger once decision is locked | Decision type, contract number | Post-decision step |
| 7 | Q&A trend analysis | Not done currently | Automated analysis of logged questions to surface common gaps | Q&A log data | Useful for SOP improvement |

### Low Priority / Future (complex, needs more context)

| # | Process Step | Notes |
|---|-------------|-------|
| 8 | RCS ICD code checking | Complex — needs integration with claims system |
| 9 | Client patching / merge | High risk — should remain manual |
| 10 | GNS screening | Compliance-sensitive — needs careful controls |

---

## Implementation Notes

- All RPA candidates are **prototype-level** — no production deployment in Sprint 2
- Human-in-the-loop is mandatory for all decision steps
- The AI automation JSON output is designed to be consumed by Power Automate but the actual PA flows are not built yet
- Priority should be on candidates #1-4 (high priority) as they are pure rule-based checks with clear inputs/outputs
