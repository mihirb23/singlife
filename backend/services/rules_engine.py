# rules_engine.py — deterministic SOP rule evaluation
# reads ALL rules from knowledge_base/sop_rules.json
# zero hardcoded thresholds or logic — if singlife changes a rule,
# they just edit the json file and restart. no code changes needed.

import json
import logging
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

RULES_FILE = Path(__file__).parent.parent.parent / 'knowledge_base' / 'sop_rules.json'

# rules cache — invalidate on file mtime change so SME edits to JSON are picked up
# without restarting the server (also avoids re-reading on every evaluate call)
_RULES_CACHE: dict = {}
_RULES_MTIME: float = 0.0


@dataclass
class StepResult:
    step_id: str
    description: str
    status: str       # Pass, Fail, Skip, Refer UW, Refer Ops, Manual Review
    finding: str
    confidence: str = "High"
    decision_impact: str = "None"
    recommended_action: Optional[str] = None


def load_rules() -> dict:
    """Load the rules config from sop_rules.json.
    Cached by file mtime — re-reads only when the file actually changes
    (avoids disk IO on every evaluate call)."""
    global _RULES_CACHE, _RULES_MTIME
    try:
        current_mtime = RULES_FILE.stat().st_mtime
        if _RULES_CACHE and current_mtime == _RULES_MTIME:
            return _RULES_CACHE
        rules = json.loads(RULES_FILE.read_text(encoding='utf-8'))
        _RULES_CACHE = rules
        _RULES_MTIME = current_mtime
        return rules
    except Exception as e:
        logger.error(f"Failed to load rules from {RULES_FILE}: {e}")
        return {}


def normalize_case(case: dict) -> dict:
    """pull out all the fields we need, handling different key names
    from UAT data vs test questions vs raw L400 exports"""
    def g(key, *alts):
        val = case.get(key)
        if val is not None:
            return val
        for a in alts:
            val = case.get(a)
            if val is not None:
                return val
        return None

    return {
        "channel": g("channel", "CHANNEL") or "QnB",
        "contract_no": g("contractNo", "CONTRACTNO", "contract_no"),
        "cnt_type": g("cntType", "CNTTYPE", "plan_code"),
        "client_no": g("clientNo", "CLIENTNO", "client_no"),
        "submission_date": g("submission_date", "submission_datetime", "SUBMISSION_DATIME"),
        "consent_timestamp": g("consent_timestamp", "myinfo_consent_timestamp"),
        "consent_valid": g("consent_valid", "Consent_Valid"),
        "identity_doc_exists": g("identity_doc_exists", "identity_doc", "MyInfo_Doc"),
        "benefit_illustration_exists": g("benefit_illustration_exists", "benefit_illustration", "BI_Doc"),
        "application_form_exists": g("application_form_exists", "application_form", "AppForm_Doc"),
        "sub_nric": g("nric", "sub_identity_id", "SUB_SECUITYNO"),
        "sub_surname": g("surname", "sub_surname", "SUB_SURNAME"),
        "sub_given_name": g("givenName", "given_name", "sub_given_name", "SUB_GIVNAME"),
        "sub_sex": g("sex", "sub_sex", "SUB_CLTSEX"),
        "sub_dob": g("dob", "sub_dob", "SUB_CLTDOB"),
        "sub_nationality": g("nationality", "sub_nationality", "SUB_NATLTY"),
        "l400_nric": g("l400_nric", "curr_identity_id", "CURR_SECUITYNO"),
        "l400_surname": g("l400_surname", "curr_surname", "CURR_SURNAME"),
        "l400_given_name": g("l400_givenName", "l400_given_name", "curr_given_name", "CURR_GIVNAME"),
        "l400_name": g("l400_name"),
        "l400_sex": g("l400_sex", "curr_sex", "CURR_CLTSEX"),
        "l400_dob": g("l400_dob", "curr_dob", "CURR_CLTDOB"),
        "l400_nationality": g("l400_nationality", "curr_nationality", "CURR_NATLTY"),
        "l400_address": g("l400_address", "CLTADDR01"),
        "l400_postcode": g("l400_postcode", "CLTPCODE"),
        "l400_phone": g("l400_phone", "TLXNO"),
        "l400_email": g("l400_email", "ZEMAILADD"),
        "followups": g("followUpCodes", "followups", "FOLLOWUPS") or [],
        "anb": g("anb", "anb_at_ccd", "ANB_AT_CCD"),
        "total_sa": g("totalAggregateSA", "total_aggregate_sa"),
        "uw_sub_std": g("uwSubStd", "uw_sub_std"),
        "decline": g("decline"),
        "postpone": g("postpone"),
        "claim_ind": g("claimInd", "claim_ind"),
    }


def norm_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip().lower()


def norm_date(val) -> str:
    if val is None:
        return ""
    s = str(val).strip().replace("/", "-")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


# -- rule executors --
# each function handles one "rule" type from the json config.
# the step config tells us WHAT to check, these functions do the HOW.

def execute_document_exists(c: dict, step_cfg: dict) -> StepResult:
    """rule: document_exists — checks if a required document is available.
    in student scope we only check metadata (exists/not exists)."""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    doc_field = step_cfg.get("document", "")
    truthy = step_cfg.get("truthy_values", [])

    # use sentinel so we can distinguish "missing key" from "explicit empty/0/False"
    _missing = object()
    val = c.get(f"{doc_field}_exists", _missing)
    if val is _missing:
        val = c.get(doc_field, _missing)

    if val is _missing or val is None:
        # compliance: missing field should NOT auto-pass — flag for human review
        return StepResult(step_id, desc, "Manual Review",
                          f"Document field '{doc_field}' missing in case data — cannot verify",
                          confidence="Low",
                          recommended_action=step_cfg.get("missing_recommended_action",
                                                           "Verify document exists in FileNet"))

    val_str = str(val).strip().lower()
    if val_str in truthy:
        return StepResult(step_id, desc, "Pass", f"Document available: {doc_field}")
    return StepResult(step_id, desc, "Fail",
                      f"Document missing: {doc_field}",
                      decision_impact=step_cfg["fail_impact"],
                      recommended_action=step_cfg.get("fail_recommended_action"))


def execute_consent_timestamp(c: dict, step_cfg: dict) -> StepResult:
    """rule: consent_timestamp — validates MyInfo consent is within max_age_days.
    see ref_myinfo_consent_rules.txt for full logic."""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    max_days = step_cfg.get("max_age_days", 365)

    # check consent_valid flag first (Y/N from test data — per May: use consent_valid column)
    consent_valid = norm_str(c.get("consent_valid"))
    if consent_valid in ("y", "yes", "true", "1"):
        return StepResult(step_id, desc, "Pass",
                          "MyInfo consent valid (consent_valid = Y)")
    if consent_valid in ("n", "no", "false", "0"):
        return StepResult(step_id, desc, "Fail",
                          "MyInfo consent invalid or expired (consent_valid = N)",
                          decision_impact=step_cfg["fail_impact"],
                          recommended_action=step_cfg.get("fail_recommended_action"))

    consent_ts = c.get("consent_timestamp")
    submission_date = c.get("submission_date")

    # if neither consent_valid nor timestamp in case data
    if not consent_ts:
        return StepResult(step_id, desc, "Pass",
                          "MyInfo consent timestamp not in case data — assumed valid for prototype",
                          confidence="Low",
                          recommended_action=step_cfg.get("missing_recommended_action"))

    if not submission_date:
        return StepResult(step_id, desc, "Manual Review",
                          "Submission date missing — cannot validate consent timestamp",
                          confidence="Low")

    try:
        # parse various date formats
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                consent_dt = datetime.strptime(str(consent_ts).strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return StepResult(step_id, desc, "Manual Review",
                              f"Cannot parse consent timestamp: {consent_ts}", confidence="Low")

        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                submit_dt = datetime.strptime(str(submission_date).strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return StepResult(step_id, desc, "Manual Review",
                              f"Cannot parse submission date: {submission_date}", confidence="Low")

        age_days = (submit_dt - consent_dt).days
        if age_days <= max_days:
            return StepResult(step_id, desc, "Pass",
                              f"Consent valid — {age_days} days old (limit: {max_days})")
        else:
            return StepResult(step_id, desc, "Fail",
                              f"Consent expired — {age_days} days old (limit: {max_days})",
                              decision_impact=step_cfg["fail_impact"],
                              recommended_action=step_cfg.get("fail_recommended_action"))
    except Exception as e:
        return StepResult(step_id, desc, "Manual Review",
                          f"Error validating consent: {e}", confidence="Low")


def execute_client_search_nric(c: dict, step_cfg: dict) -> StepResult:
    """rule: client_search_nric — checks NRIC search returns exactly 1 result.
    in prototype, we check if sub_nric matches l400_nric (simulating search)."""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]

    sub_nric = norm_str(c.get("sub_nric"))
    l400_nric = norm_str(c.get("l400_nric"))

    if not sub_nric:
        return StepResult(step_id, desc, "Fail",
                          "NRIC not provided in submission data",
                          decision_impact=step_cfg["fail_impact"])

    if not l400_nric:
        return StepResult(step_id, desc, "Manual Review",
                          "No L400 NRIC to compare — cannot verify client search",
                          confidence="Low")

    if sub_nric == l400_nric:
        return StepResult(step_id, desc, "Pass",
                          f"NRIC search: 1 result found (matched)")
    else:
        return StepResult(step_id, desc, "Fail",
                          f"NRIC mismatch: submitted {c.get('sub_nric')} vs L400 {c.get('l400_nric')}",
                          decision_impact=step_cfg["fail_impact"],
                          recommended_action=step_cfg.get("fail_recommended_action"))


def execute_client_record_found(c: dict, step_cfg: dict) -> StepResult:
    """rule: client_record_found — just checks if a client number exists"""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    if c["client_no"]:
        return StepResult(step_id, desc, "Pass", f"Client {c['client_no']} found on L400")
    return StepResult(step_id, desc, "Fail", "No client record found",
                      decision_impact=step_cfg["fail_impact"])


def execute_field_match(c: dict, step_cfg: dict) -> StepResult:
    """rule: field_match — compares submitted fields against L400 fields.
    field mapping comes from step config in sop_rules.json.

    Compliance note: if a required field is missing on BOTH sides, we don't
    silently pass — return Manual Review so an operator can verify rather than
    let an unverifiable case slip through to STP."""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    fields_to_check = step_cfg.get("fields", [])
    cfg_field_map = step_cfg.get("field_mapping", {})
    mismatches = []
    matched = []
    skipped = []  # fields we couldn't compare because data was missing

    for field in fields_to_check:
        fm = cfg_field_map.get(field, {})

        # name matching is a special type — compares surname + given name
        if fm.get("type") == "name_match":
            name_checked = False
            if c["sub_surname"] and c["l400_surname"]:
                if norm_str(c["sub_surname"]) != norm_str(c["l400_surname"]):
                    mismatches.append(f"Surname: {c['sub_surname']} vs {c['l400_surname']}")
                else:
                    matched.append("Surname")
                name_checked = True
            if c["sub_given_name"] and c["l400_given_name"]:
                if norm_str(c["sub_given_name"]) != norm_str(c["l400_given_name"]):
                    mismatches.append(f"Given Name: {c['sub_given_name']} vs {c['l400_given_name']}")
                else:
                    matched.append("Given Name")
                name_checked = True
            if not name_checked and c["l400_name"]:
                full_sub = f"{c['sub_surname'] or ''} {c['sub_given_name'] or ''}".strip()
                if full_sub and norm_str(full_sub) != norm_str(c["l400_name"]):
                    mismatches.append(f"Name: {full_sub} vs {c['l400_name']}")
                elif full_sub:
                    matched.append("Name")
                    name_checked = True
            if not name_checked:
                skipped.append(field)
            continue

        # standard field comparison — keys come from config
        sub_key = fm.get("sub_key")
        l400_key = fm.get("l400_key")
        is_date = fm.get("is_date", False)
        if not sub_key or not l400_key:
            continue
        sub_val = c.get(sub_key)
        l400_val = c.get(l400_key)
        if sub_val and l400_val:
            if is_date:
                match = norm_date(sub_val) == norm_date(l400_val)
            else:
                match = norm_str(sub_val) == norm_str(l400_val)
            if match:
                matched.append(field.upper())
            else:
                mismatches.append(f"{field.upper()}: {sub_val} vs {l400_val}")
        else:
            skipped.append(field)

    if mismatches:
        return StepResult(step_id, desc, "Fail",
                          f"Mismatch: {'; '.join(mismatches)}",
                          decision_impact=step_cfg["fail_impact"],
                          recommended_action=step_cfg.get("fail_recommended_action"))
    if skipped:
        # all the matched ones passed, but at least one field couldn't be verified.
        # set decision_impact = step's fail_impact so derive_decision routes it through
        # the priority logic — otherwise Manual Review status alone is invisible to the
        # final decision (Manual Review isn't in fail_statuses), which silently lets
        # the case slip through to Standard.
        return StepResult(step_id, desc, "Manual Review",
                          f"Cannot verify {', '.join(skipped)} — field(s) missing on submission and/or L400. "
                          f"Verified: {', '.join(matched) or 'none'}",
                          confidence="Low",
                          decision_impact=step_cfg["fail_impact"],
                          recommended_action=step_cfg.get("missing_recommended_action",
                                                          f"Verify {', '.join(skipped)} manually before STP"))
    return StepResult(step_id, desc, "Pass",
                      f"All fields match: {', '.join(matched)}")


def execute_all_followups_resolved(c: dict, step_cfg: dict) -> StepResult:
    """rule: all_followups_resolved — checks every follow-up code status"""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    followups = c.get("followups") or []

    # handle string format like "CSL:O;F45:R"
    if isinstance(followups, str):
        parsed = []
        for pair in followups.split(";"):
            pair = pair.strip()
            if ":" in pair:
                code, status = pair.split(":", 1)
                parsed.append({"code": code.strip(), "status": status.strip()})
        followups = parsed

    resolved_status = step_cfg.get("resolved_status", "R")

    if not followups:
        return StepResult(step_id, desc, "Pass", "No follow-up codes present")

    outstanding = [f for f in followups if str(f.get("status", "")).upper() != resolved_status]
    resolved = [f for f in followups if str(f.get("status", "")).upper() == resolved_status]

    if not outstanding:
        codes = ", ".join(f"{f['code']}:{resolved_status}" for f in resolved)
        return StepResult(step_id, desc, "Pass", f"All resolved: {codes}")

    codes = ", ".join(f"{f['code']}:{f['status']}" for f in outstanding)
    return StepResult(step_id, desc, "Fail", f"Outstanding: {codes}",
                      decision_impact=step_cfg["fail_impact"],
                      recommended_action=step_cfg.get("fail_recommended_action"))


def execute_threshold_check(c: dict, step_cfg: dict) -> StepResult:
    """rule: threshold_check — evaluates ANB/SA against thresholds from json"""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    anb = c.get("anb")
    sa = c.get("total_sa")

    if anb is None or sa is None:
        return StepResult(step_id, desc, "Manual Review",
                          f"Missing data — ANB: {anb}, SA: {sa}", confidence="Low",
                          recommended_action=step_cfg.get("missing_recommended_action"))

    anb = int(anb)
    sa = float(sa)

    # evaluate each threshold from the json config (order matters — first match wins)
    for threshold in step_cfg.get("thresholds", []):
        condition = threshold["condition"]
        if eval_condition(condition, anb, sa):
            result_status = threshold["result"]
            if result_status in ("Continue", "Pass"):
                return StepResult(step_id, desc, "Pass",
                                  f"{threshold['label']} (ANB={anb}, SA=${sa:,.0f})")
            else:
                return StepResult(step_id, desc, result_status,
                                  f"{threshold['label']} (ANB={anb}, SA=${sa:,.0f})",
                                  decision_impact=step_cfg["fail_impact"])

    # no threshold matched — default to Refer UW (conservative)
    return StepResult(step_id, desc, "Refer UW",
                      f"ANB {anb}, SA ${sa:,.0f} — no matching threshold rule",
                      decision_impact=step_cfg["fail_impact"])


def eval_condition(condition: str, anb: int, sa: float) -> bool:
    """evaluate a threshold condition string like 'sa > 6000' or 'anb >= 31 and sa > 5000'.
    only allows anb/sa variables and basic comparisons — no arbitrary code execution"""
    allowed = {"anb": anb, "sa": sa}
    try:
        return bool(eval(condition, {"__builtins__": {}}, allowed))
    except Exception:
        return False


def execute_uw_indicator(c: dict, step_cfg: dict) -> StepResult:
    """rule: uw_indicator — checks if a UW field value is in pass or fail list"""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    field = step_cfg["field"]
    label = step_cfg["label"]
    val = c.get(field)

    if val is None:
        return StepResult(step_id, desc, "Manual Review",
                          f"{label} not provided", confidence="Low")

    val_upper = str(val).strip().upper()
    pass_vals = [v.upper() for v in step_cfg.get("pass_values", [])]
    fail_vals = [v.upper() for v in step_cfg.get("fail_values", [])]

    if val_upper in pass_vals:
        return StepResult(step_id, desc, "Pass", f"{label} = {val} — Continue")
    elif val_upper in fail_vals:
        return StepResult(step_id, desc, step_cfg["fail_impact"], f"{label} = {val} — {step_cfg['fail_impact']}",
                          decision_impact=step_cfg["fail_impact"])
    else:
        return StepResult(step_id, desc, "Manual Review",
                          f"{label} = {val} — unexpected value", confidence="Low")


def execute_rcs_trigger(c: dict, step_cfg: dict) -> StepResult:
    """rule: rcs_trigger — checks if only the trigger field is flagged while all others are clear.
    trigger value, clear values, and impacts all come from config."""
    step_id = step_cfg["_id"]
    desc = step_cfg["description"]
    trigger_val = norm_str(c.get(step_cfg["trigger_field"]))
    expected_trigger = step_cfg.get("trigger_value", "y")
    clear_values = step_cfg.get("clear_values", [])

    if trigger_val != expected_trigger:
        return StepResult(step_id, desc, "Skip",
                          f"{step_cfg.get('label', step_cfg['trigger_field'])} is not {expected_trigger.upper()} — step not triggered")

    others_clear = all(
        norm_str(c.get(f)) in clear_values
        for f in step_cfg.get("other_fields", [])
    )

    if others_clear:
        return StepResult(step_id, desc, "Pass",
                          step_cfg.get("pass_condition", "Trigger condition met — further check required"),
                          decision_impact=step_cfg.get("pass_impact", "RCS Required"),
                          recommended_action=step_cfg.get("pass_recommended_action"))
    return StepResult(step_id, desc, step_cfg["fail_impact"],
                      f"{step_cfg['trigger_field']} flagged AND other indicators also flagged — {step_cfg['fail_impact']}",
                      decision_impact=step_cfg["fail_impact"])


# map rule type strings from json to executor functions
RULE_EXECUTORS = {
    "document_exists": execute_document_exists,
    "consent_timestamp": execute_consent_timestamp,
    "client_search_nric": execute_client_search_nric,
    "client_record_found": execute_client_record_found,
    "field_match": execute_field_match,
    "all_followups_resolved": execute_all_followups_resolved,
    "threshold_check": execute_threshold_check,
    "uw_indicator": execute_uw_indicator,
    "rcs_trigger": execute_rcs_trigger,
}


def derive_decision(results: list, rules: dict) -> dict:
    """aggregate step results into a final decision.
    ALL business logic reads from sop_rules.json decision_logic section.
    the engine interprets the config — no hardcoded step IDs, codes, or priorities."""
    logic = rules.get("decision_logic", {})
    decision_map = rules.get("decision_mapping", {})

    # which statuses count as failures — from config
    fail_statuses = logic.get("fail_statuses", [])
    failed_steps = [r.step_id for r in results if r.status in fail_statuses]

    # extract outstanding follow-ups from the configured follow-up step
    fup_step_id = logic.get("followup_step_id")
    outstanding_followups = ""
    if fup_step_id:
        for r in results:
            if r.step_id == fup_step_id and r.status in fail_statuses:
                # strip any leading "<word>:" label (e.g. "Outstanding: ") without
                # hardcoding the exact phrase from the executor — robust to wording changes
                finding = r.finding
                if ":" in finding:
                    label, _, rest = finding.partition(":")
                    # only strip if it looks like a short label (not a real value)
                    if len(label) < 30:
                        finding = rest.strip()
                outstanding_followups = finding

    # check if any compliance trigger codes are present in the follow-up step finding.
    # use word-boundary regex so "C09 cleared" or "no C09" don't false-positive.
    compliance_codes = logic.get("compliance_trigger_codes", [])
    has_compliance_hit = False
    if fup_step_id and compliance_codes:
        import re as _re
        for r in results:
            if r.step_id == fup_step_id and r.status in fail_statuses:
                # match "C09" or "C09:O" but not "C091" or descriptive phrases
                for code in compliance_codes:
                    pattern = r"\b" + _re.escape(code) + r"(?::[A-Z])?\b"
                    if _re.search(pattern, r.finding):
                        # avoid false positive on negated phrases
                        finding_lower = r.finding.lower()
                        if not any(neg in finding_lower for neg in ("no " + code.lower(),
                                                                     code.lower() + " cleared",
                                                                     "not " + code.lower())):
                            has_compliance_hit = True
                            break

    # walk the decision priority list from config to find the matching decision
    key = "Standard"
    for rule in logic.get("decision_priority", []):
        condition = rule.get("condition")

        if condition == "any_step_has_impact":
            impact_val = rule.get("impact_value", "")
            also_status = rule.get("also_check_status", "")
            extra_impacts = rule.get("additional_impacts", [])
            if any(r.decision_impact == impact_val or r.status == also_status or
                   r.decision_impact in extra_impacts for r in results):
                key = rule["key"]
                break

        elif condition == "compliance_code_outstanding":
            if has_compliance_hit:
                key = rule["key"]
                break

        elif condition == "default":
            key = rule["key"]
            break

    cfg = decision_map.get(key, {})

    # automation trigger from per-decision mapping in config
    trigger_map = logic.get("automation_trigger_by_decision", {})
    can_automate = trigger_map.get(key, "No") == "Yes"

    # decision label and ops_outcome from json config
    decision_label = cfg.get("decision_label", key)
    ops_outcome = cfg.get("ops_outcome_detail", cfg.get("workflow_action", key))

    # build decision_reason dynamically from actual step results
    if not failed_steps:
        decision_reason = f"All applicable steps passed, no outstanding issues. Step 9A {decision_label}."
    else:
        trigger_parts = []
        for r in results:
            if r.step_id in failed_steps:
                trigger_parts.append(f"{r.finding} (Step {r.step_id})")
        step_ids = "/".join(failed_steps)
        decision_reason = f"{'; '.join(trigger_parts)}. Step {step_ids} -> {decision_label}."

    return {
        "overall_decision": key,
        "ops_outcome": ops_outcome,
        "dotsphere_steps": cfg.get("dotsphere_steps", []),
        "human_review": cfg.get("human_review", True),
        "automation_trigger": "Yes" if can_automate else "No",
        "steps_failed": failed_steps,
        "decision": decision_label,
        "decision_reason": decision_reason,
        "outstanding_followups": outstanding_followups,
    }


def evaluate_case(case_data: dict) -> dict:
    """main entry point — loads rules from json, runs every applicable step,
    returns structured results for claude to explain"""
    rules = load_rules()
    if not rules:
        return {"error": "Failed to load sop_rules.json"}

    c = normalize_case(case_data)
    channel = c["channel"]

    # get channel gating from json
    gating = rules.get("channel_gating", {}).get(channel)
    if not gating:
        gating = rules.get("channel_gating", {}).get("EzSub", {})

    steps_cfg = rules.get("steps", {})
    results = []
    skipped = []

    # run each step defined in the json
    for step_id, step_cfg in steps_cfg.items():
        flag = gating.get(step_id, "N")
        if flag == "Y":
            rule_type = step_cfg.get("rule")
            executor = RULE_EXECUTORS.get(rule_type)
            if executor:
                # don't mutate the cached step_cfg dict — copy it so concurrent
                # requests don't trample each other's "_id" attribute
                cfg_with_id = {**step_cfg, "_id": step_id}
                result = executor(c, cfg_with_id)
                results.append(result)
            else:
                logger.warning(f"No executor for rule type: {rule_type}")
        else:
            reason = "NA for all channels" if flag == "NA" else f"{channel}={flag}"
            skipped.append({"step_id": step_id, "reason": f"Channel gating: {reason}"})

    # also record skipped steps that aren't in our evaluatable steps
    all_gated_steps = set(gating.keys())
    evaluated_ids = {r.step_id for r in results} | {s["step_id"] for s in skipped}
    for step_id in all_gated_steps - evaluated_ids:
        flag = gating[step_id]
        if flag != "Y":
            reason = "NA for all channels" if flag == "NA" else f"{channel}={flag}"
            skipped.append({"step_id": step_id, "reason": f"Channel gating: {reason}"})

    decision = derive_decision(results, rules)

    return {
        "channel": channel,
        "contract_no": c["contract_no"],
        "cnt_type": c["cnt_type"],
        "sop_applied": rules.get("sop_id", "SOP-NBIG-STP-001"),
        "sop_rule_evaluation": [
            {
                "step_id": r.step_id,
                "description": r.description,
                "status": r.status,
                "finding": r.finding,
                "confidence": r.confidence,
                "decision_impact": r.decision_impact,
                "recommended_action": r.recommended_action,
            }
            for r in results
        ],
        "steps_skipped": sorted(skipped, key=lambda s: s["step_id"]),
        "overall_decision": decision["overall_decision"],
        "ops_outcome": decision["ops_outcome"],
        "dotsphere_steps": decision["dotsphere_steps"],
        "automation_trigger": decision["automation_trigger"],
        "steps_failed": decision["steps_failed"],
        "decision": decision["decision"],
        "decision_reason": decision["decision_reason"],
        "outstanding_followups": decision["outstanding_followups"],
    }
