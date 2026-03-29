# Knowledge Gap / Ambiguity Log

Tracks missing or unclear SOP information that limits the AI's accuracy.
Updated whenever we find something the AI can't answer confidently.

---

| # | SOP Reference | Issue | Impact | Suggested Clarification | Status |
|---|--------------|-------|--------|------------------------|--------|
| 1 | Step 8H — RCS checks | ICD code pass/fail list is not included in the SOP. AI cannot determine whether specific claim ICD codes should pass or be referred to UW. | Cannot complete Jet UW evaluation when Claim Ind = Y | Need the full ICD code classification list (which codes pass, which refer to UW) | Open |
| 2 | Step 3A — Client search | SOP says "Flag issue; manual review" when >1 results found, but doesn't define the resolution process for multiple matches | AI can flag but can't recommend specific resolution steps | Document the merge/resolution procedure for duplicate NRIC hits | Open |
| 3 | Step 7 — Follow-up codes | Only F45, CSL, C09, AT3 are defined. Other FUP codes exist in UAT data but are not documented in the SOP | AI may encounter unknown codes and can't interpret them | Need complete list of follow-up codes with descriptions and resolution actions | Open |
| 4 | Step 5B — Race update | SOP says "update Race from OTH to correct value" but doesn't specify what the correct values are or when this applies | AI can't validate race field or recommend the correct value | Need race code reference table (CHI, MAL, IND, OTH, etc.) and rules for when to update | Open |
| 5 | Step 6A-6I — Contract checks | These steps are marked NA for all channels (QnB, EzSub, Hardcopy) in the applicability table, but the checks clearly happen at contract level | Confusing — does NA mean "not checked" or "checked differently"? | Clarify what NA means in this context and when premium/payment checks actually apply | Open |
| 6 | Step 5A — Name sequence | "Check if client name sequence on L400 matches MyInfo Consent Form" — not clear what "name sequence" means vs just name matching | AI may misinterpret this as a simple name match vs a specific ordering check | Define what name sequence means (e.g., surname-first vs given-name-first) | Open |
| 7 | General — EzSub vs Hardcopy | SOP has channel-specific rules (QnB/EzSub/Hardcopy) but the UAT data doesn't have a clear channel field — we infer from cntType | May misclassify the channel for evaluation | Confirm: is cntType (EYA/EYB) sufficient to determine channel, or is there another field? | Open |
| 8 | Step 8B — SA thresholds | Rules reference "Total Aggregate SA" but for LTC (Long Term Care) products, the SA is a monthly benefit amount (e.g., $3,000/month = $36,000/year). Unclear if the $6,000/$5,000 thresholds apply to the monthly benefit or the aggregated SA on L400 | Could miscalculate whether a case needs UW referral | Clarify: do Jet UW SA thresholds apply to the monthly benefit amount or the Total Aggregate SA shown on the Client Underwriting Enquiries screen? | Open |

---

## How this log is used

1. When the AI encounters a question it can't answer confidently, it flags it in the response
2. Q&A logs (`/api/logs`) capture these interactions automatically
3. We manually add confirmed gaps to this log
4. Gaps are shared with Singlife SMEs (Sharon/May) for clarification
5. Once clarified, the SOP is updated and the gap is marked Resolved
