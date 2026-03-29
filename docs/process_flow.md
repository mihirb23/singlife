# End-to-End Process Flow — AI Ops Concept

Shows how data flows through the system from application submission to decision output.

---

## As-Is Flow (Current — No AI)

```
New Application Submitted (QnB / EzSub / Hardcopy)
        |
        v
Ops Staff opens documents on FileNet + DotSphere
        |
        v
Ops Staff manually checks L400 fields vs application form
  - client number, NRIC, name, DOB, sex, address, etc.
  - premium amounts, payment modes
        |
        v
Ops Staff checks follow-up codes on L400
  - are all FUPs resolved (R)?
        |
        v
Ops Staff opens Client Underwriting Enquiries on L400
  - checks ANB, SA thresholds
  - checks UW Sub-std, Decline, Postpone, Claim Ind
        |
        v
Ops Staff makes decision based on experience + SOP knowledge
  - Standard / Refer to UW / GNS / Withdrawal
        |
        v
Ops Staff locks case in DotSphere
```

**Problems:** relies on individual SOP knowledge, inconsistent answers, senior staff bottlenecked on routine checks.

---

## To-Be Flow (With AI Overlay)

```
New Application Submitted (QnB / EzSub / Hardcopy)
        |
        v
+--------------------------------------+
| DATA EXTRACTION                      |
| L400 data pulled via Power Automate  |
| Application form data from DotSphere |
| Documents indexed from FileNet       |
+--------------------------------------+
        |
        v
+--------------------------------------+
| AI KNOWLEDGE BASE                    |
| SOPs loaded as structured text       |
| Policy docs loaded                   |
| knowledge_base/*.txt                 |
+--------------------------------------+
        |
        v
+--------------------------------------+
| AI OPS BRAIN (Claude LLM)           |
| Receives: case data + SOP rules     |
| Evaluates: each SOP step            |
| Outputs:                             |
|   - Pass/Fail per rule              |
|   - Overall decision                |
|   - Ops instructions                |
|   - Automation trigger JSON         |
|   - Knowledge gaps (if any)         |
+--------------------------------------+
        |
        +-----> Ops Staff reviews AI recommendation
        |         - approves / overrides / adds context
        |         - locks case in DotSphere
        |
        +-----> Q&A Log (logs/qa_log.jsonl)
        |         - captures every interaction
        |         - feeds back into SOP improvements
        |
        +-----> Automation Trigger (JSON output)
                  - could trigger Power Automate flow
                  - route to correct team
                  - send notifications
                  - update tracking systems
```

---

## Integration Points

| Point | System | What happens | AI role |
|-------|--------|-------------|---------|
| Input | L400 | Client/contract data extracted | AI receives this data for evaluation |
| Input | FileNet | Documents retrieved | AI checks if required docs are present |
| Input | DotSphere | Application form data | AI compares against L400 |
| Processing | Claude API | SOP evaluation runs | AI evaluates each rule step-by-step |
| Output | DotSphere | Decision locked | Ops staff acts on AI recommendation |
| Output | Power Automate | Workflow triggered | JSON payload could trigger automated routing |
| Logging | Q&A Log | Interaction recorded | Feeds learning loop for SOP improvement |

---

## Automation Trigger JSON (output format)

When the AI completes an evaluation, it produces a structured JSON payload:

```json
{
  "policyNumber": "G0406789",
  "decision": "StandardWithRequirements",
  "outstandingItems": ["Name mismatch — verify with client", "CSL follow-up unresolved"],
  "sopStepsFailed": ["5C", "7B"],
  "recommendedAction": "Request updated client information, resolve CSL follow-up"
}
```

This JSON could be consumed by Power Automate to:
- Route the case to the right ops queue
- Send email notifications for outstanding items
- Update a SharePoint tracking list
- Flag cases that need senior review

---

## What the AI does NOT do

- Does not write to L400, FileNet, or DotSphere
- Does not approve or reject cases — only recommends
- Does not access live production systems
- Does not fix data mismatches — only flags them
- Human judgment remains the final authority
