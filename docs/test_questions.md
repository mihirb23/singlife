# Test Question Set & Evaluation Checklist

Used to validate that the AI prototype gives correct, SOP-grounded answers.
Each question has an expected answer so we can check correctness during demo.

---

## Part A: Common Ops Questions (Chat Mode)

### Q1: What checks are required for QnB CareShield cases?
**Expected:** For QnB channel, Steps 1A-1C and 2A are N/A (NO). The applicable checks are:
- 4A-4B: Duplicate client checks (search by name, verify DOB/sex)
- 5C: Client information checks (sex, address, mobile, email, nationality, NRIC, DOB)
- 7B: Follow-up code checks (all must be R)
- 8B-8H: Jet underwriting (ANB/SA thresholds, UW indicators)
Should reference SOP-NBIG-STP-001 step applicability table.

### Q2: What are the Jet underwriting SA thresholds?
**Expected:**
- SA <= $6,000 AND ANB 18-30: Continue (pass)
- SA > $6,000: Refer to UW
- SA > $5,000 AND ANB >= 31: Refer to UW
Must cite Step 8B.

### Q3: When should a case be referred to UW?
**Expected:** Refer to UW when any of these are true:
- SA exceeds thresholds (Step 8B)
- UW Sub-std = Y or M (Step 8C)
- Decline = Y or M (Step 8D)
- Postpone = Y or M (Step 8E)
- Claim Ind = Y or M AND not the only indicator (Step 8F)
- RCS check result = Refer (Step 8H)
Should reference Decision Outcome C.

### Q4: What happens if a client's email doesn't match between L400 and the application form?
**Expected:** This is a Step 5C failure — email mismatch is an outstanding item. The case would go to Decision B (Standard with Further Requirements). The AI should flag it but NOT fix it autonomously. Email is important because the client needs it for MySinglife account registration.

### Q5: What does follow-up code CSL mean?
**Expected:** CSL = CareShield Life related follow-up. Referenced in Step 7 (Follow Up Code Checks). If status is 'O' (open), it means there's an outstanding CareShield-related item that needs resolution before the case can proceed.

---

## Part B: Ambiguous / Edge Case Questions (Chat Mode)

### Q6: Can I approve a case if the only UW indicator flagged is Claim Ind = Y?
**Expected:** Not automatically — per Steps 8F and 8G, if only Claim Ind = Y and all other indicators (Sub-std, Decline, Postpone) = N, then RCS checks are required (Step 8H). The decision depends on whether the ICD codes pass or refer. Should NOT give a definitive yes/no without RCS result.

### Q7: What if the client has two records on L400?
**Expected:** This triggers Step 3A (>1 results) → Manual Review required. Then Step 4A-4C for duplicate client checks. Client patching (merge/void) may be needed (Step 4C). The AI should flag this for human resolution, not attempt to resolve it.

### Q8: What's the process for a withdrawal request?
**Expected:** Decision Outcome F — specific steps:
1. Go to Contract Issue screen on L400
2. Enter Contract Number
3. Action = B
4. Reason = N001
5. Go to DotSphere
6. Select Decision: Withdrawal Request Received

### Q9: What is the ICD pass/fail list for RCS checks?
**Expected:** This should be flagged as a **knowledge gap**. The SOP references RCS checks (Step 8H) but does not contain the actual ICD code pass/fail list. AI should say it cannot answer and log the gap.

---

## Part C: Case Evaluation (Evaluate Mode)

### Q10: Clean QnB case — all fields match, all follow-ups resolved
```json
{
  "contractNo": "G0401259",
  "cntType": "EYA",
  "channel": "QnB",
  "clientNo": "55164576",
  "nric": "S0287421J",
  "surname": "Ong",
  "givenName": "Cs Eden",
  "sex": "F",
  "dob": "1987-05-12",
  "nationality": "SG",
  "l400_nric": "S0287421J",
  "l400_surname": "Ong",
  "l400_givenName": "Cs Eden",
  "l400_sex": "F",
  "l400_dob": "1987-05-12",
  "l400_nationality": "SG",
  "followUpCodes": [{"code": "CSL", "status": "R"}, {"code": "F45", "status": "R"}],
  "anb": 39,
  "totalAggregateSA": 3000,
  "uwSubStd": "N",
  "decline": "N",
  "postpone": "N",
  "claimInd": "N"
}
```
**Expected Decision:** Standard (Decision A)
- All client fields match → 5C Pass
- All follow-ups = R → 7B Pass
- SA $3,000 < $6,000 and ANB 39 but SA < $5,000 → 8B Pass
- All UW indicators N → 8C-8F Pass
- No outstanding items → Decision A

### Q11: Case with name mismatch and open follow-up
```json
{
  "contractNo": "G0406789",
  "cntType": "EYA",
  "channel": "QnB",
  "clientNo": "55167349",
  "nric": "S8483123I",
  "surname": "Long",
  "givenName": "Quan Zhi",
  "sex": "M",
  "dob": "1988-08-08",
  "nationality": "SG",
  "l400_nric": "S8483123I",
  "l400_surname": "Test",
  "l400_givenName": "Client Fields",
  "l400_sex": "M",
  "l400_dob": "1988-08-08",
  "l400_nationality": "SG",
  "followUpCodes": [{"code": "CSL", "status": "O"}],
  "anb": 38,
  "totalAggregateSA": 8000,
  "uwSubStd": "N",
  "decline": "N",
  "postpone": "N",
  "claimInd": "N"
}
```
**Expected Decision:** Refer to UW (Decision C)
- Name mismatch (Long Quan Zhi vs Test Client Fields) → 5C Fail
- CSL follow-up still open (O) → 7B Fail
- SA $8,000 > $6,000 → 8B Fail → Refer to UW
- Even without SA issue, the outstanding items would make it Decision B at minimum

### Q12: Case with UW indicator flagged
```json
{
  "contractNo": "G0403388",
  "cntType": "EYB",
  "channel": "QnB",
  "clientNo": "55164974",
  "nric": "S7898363I",
  "surname": "Cho",
  "givenName": "Ds Scs Alyssa",
  "sex": "F",
  "dob": "1984-07-19",
  "nationality": "SG",
  "l400_nric": "S7898363I",
  "l400_surname": "Cho",
  "l400_givenName": "Ds Scs Alyssa",
  "l400_sex": "F",
  "l400_dob": "1984-07-19",
  "l400_nationality": "SG",
  "followUpCodes": [{"code": "CSL", "status": "R"}],
  "anb": 42,
  "totalAggregateSA": 4000,
  "uwSubStd": "N",
  "decline": "Y",
  "postpone": "N",
  "claimInd": "N"
}
```
**Expected Decision:** Refer to UW (Decision C)
- All client fields match → 5C Pass
- Follow-ups resolved → 7B Pass
- SA $4,000 < $5,000 → 8B Pass (ANB 42 but SA under threshold)
- Decline = Y → 8D Fail → Refer to UW

---

## Evaluation Checklist

When reviewing AI responses, check:

| Criteria | What to look for |
|----------|-----------------|
| Correctness | Does the answer match the SOP rules? |
| Completeness | Are all applicable steps evaluated? |
| Citations | Does it reference specific SOP steps? |
| No hallucination | Does it stick to knowledge base content only? |
| Knowledge gaps flagged | When info is missing, does it say so instead of guessing? |
| Format compliance | Does evaluation follow the 5-part format? |
| Actionable output | Are the ops instructions clear enough to act on? |
