# claude_service.py — hybrid architecture: rules engine + RAG + LLM
# the rules engine handles deterministic SOP checks (from sop_rules.json)
# RAG retrieves relevant doc chunks (instead of stuffing everything in)
# claude just does the reasoning and explanation part
# NTU x Singlife veNTUre Sprint 2

import os
import json
import logging
from pathlib import Path
from typing import Iterator, List, Dict
from datetime import datetime

from anthropic import Anthropic
from dotenv import load_dotenv

from services.rules_engine import evaluate_case
from services.rag_service import VectorStore
from services.privacy_filter import PrivacyFilter

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env', override=True)

logger = logging.getLogger(__name__)

KB_DIR = Path(__file__).parent.parent.parent / 'knowledge_base'
LOG_DIR = Path(__file__).parent.parent.parent / 'logs'


MAX_CONVERSATION_MESSAGES = 20  # keep last N messages to avoid blowing context window
MAX_MESSAGE_CHARS = 4000  # truncate individual messages longer than this


def _trim_messages(messages: list) -> list:
    """Keep conversation within context limits.
    Preserves first message + last N messages. Truncates long assistant messages."""
    if len(messages) <= MAX_CONVERSATION_MESSAGES:
        trimmed = messages
    else:
        trimmed = [messages[0]] + messages[-(MAX_CONVERSATION_MESSAGES - 1):]

    result = []
    for m in trimmed:
        content = m.get('content', '')
        if len(content) > MAX_MESSAGE_CHARS and m.get('role') != 'user':
            result.append({**m, 'content': content[:MAX_MESSAGE_CHARS] + '\n\n[...truncated]'})
        else:
            result.append(m)
    return result


def load_knowledge_base() -> List[Dict]:
    """loads all txt files for the doc list in the sidebar.
    the actual retrieval for prompts now goes through RAG"""
    KB_DIR.mkdir(exist_ok=True)
    files = sorted(KB_DIR.glob('*.txt'))
    doc_info = []
    for f in files:
        try:
            text = f.read_text(encoding='utf-8').strip()
            doc_info.append({
                'name': f.stem.replace('_', ' ').title(),
                'filename': f.name,
                'chars': len(text),
            })
        except Exception as e:
            logger.error(f"Failed to read {f.name}: {e}")
    return doc_info


def _trim_messages(messages: list) -> list:
    """keep conversation within context limits.
    preserves the first message (initial context) and last N messages."""
    if len(messages) <= MAX_CONVERSATION_MESSAGES:
        trimmed = messages
    else:
        trimmed = [messages[0]] + messages[-(MAX_CONVERSATION_MESSAGES - 1):]

    # truncate overly long individual messages
    result = []
    for m in trimmed:
        content = m.get('content', '')
        if len(content) > MAX_MESSAGE_CHARS and m.get('role') != 'user':
            result.append({**m, 'content': content[:MAX_MESSAGE_CHARS] + '\n\n[...truncated for context limit]'})
        else:
            result.append(m)
    return result


SYSTEM_PROMPT_BASE = """You are the **Singlife AI Operations Assistant** — an intelligent operations copilot for insurance professionals.

## Your Role
You work as part of a hybrid architecture:
- **Rules Engine** handles deterministic SOP checks (field matching, thresholds, follow-up status)
- **RAG** retrieves relevant SOP content for your context
- **You (LLM)** provide reasoning, explanations, and handle Q&A

## For Case Evaluation (when rules engine results are provided)
You will receive pre-computed rules engine results. Your job is to:
1. Explain each step result in clear, human-readable language
2. Add context from the SOP documents provided
3. Flag any knowledge gaps or assumptions
4. Present the final decision with actionable DotSphere/L400 steps
5. Output structured JSON at the end

Format your response as:
**1. SOP Rule Evaluation** — explain each step with tables
**2. Overall Decision** — one of: Standard | Standard with Further Requirements | Refer to UW | Trigger GNS | Withdrawal
**3. Ops Outcome** — what the processor should do next
**4. Automation Trigger** — Yes or No (use the automation_trigger_by_decision mapping from sop_rules.json in the knowledge base)
**5. Notes** — skipped steps, knowledge gaps, assumptions

## For General Q&A (no rules engine)
- Use ONLY the provided SOP context below — do NOT guess
- Cite specific SOP steps, sections, or documents
- If the answer isn't in the context, say so and flag as knowledge gap
- If the question is ambiguous, ask clarifying questions

## Critical Rules — ANTI-HALLUCINATION
- NEVER guess or use external knowledge
- NEVER fix data autonomously — flag mismatches, humans decide
- Always cite Step IDs for traceability
- Use plan codes (EYA, EYB) not plan names
- If a rule/threshold is missing — flag as Knowledge Gap, do NOT guess
- NEVER expand abbreviations or invent definitions for follow-up codes or step descriptions
- Use ONLY the exact definitions from the context provided. If a definition is not in the context, say "definition not in retrieved context" rather than guessing.

## Confirmed Follow-Up Code Definitions (ALWAYS use these — do NOT invent alternatives)
- CSL = Basic CSL Plan Status check (EYA/EYB category)
- C09 = Compliance GNS Rescreening (Compliance category) — drives GNS/Compliance decision path
- F45 = PF-Premium differ from PI / premium mismatch (Premium category)
- AT3 = DVM Agent Tier T3 (DVM category)
- GNS = Global Naming Screening (Compliance category)

## Confirmed Step Descriptions (ALWAYS use these — do NOT invent alternatives)
- 1A: Open Identity Document on FileNet
- 1B: Open Benefit Illustration on FileNet
- 1C: Open Application Form on DotSphere
- 2A: Check MyInfo Consent Form Timestamp validity
- 3A: Search client on L400 using NRIC/License
- 4A: Search client by Surname + Given Name
- 4B: Check DOB and Sex vs Application Form
- 4C: Client patching (merge/void duplicates) — Human-only
- 5A: Check client name sequence vs MyInfo — NO for ALL channels
- 5B: Update Race from OTH to correct value — NO for ALL channels
- 5C: Validate key client fields (Sex, Address, SMS, Email, Nationality, NRIC, DOB)
- 5D: Update incorrect fields on L400 — Human-only, NO for ALL channels
- 6A-6I: Contract Information Checks — NA for ALL channels (system-handled)
- 7A: Open Proposal Follow-ups screen
- 7B: Check if all follow-ups are R (Resolved)
- 7C: Take required follow-up action — NO for ALL channels
- 8A: Open Client Underwriting Inquiries screen
- 8B: Check ANB and Total Aggregate SA
- 8C: Check UW Sub-std indicator
- 8D: Check Decline indicator
- 8E: Check Postpone indicator
- 8F: Check Claim Ind indicator
- 8G: Check if only Claim Ind = Y (all others N) — RCS trigger
- 8H: RCS checks (ICD codes) — decision step
- 9A: Take decision and lock case

## Channel Gating Summary
- QnB skips: 1A, 1B, 1C, 2A, 3A, 4C, 5A, 5B, 5D, 7C, 8H (+ 6A-6I = NA)
- EzSub/Hardcopy skip: 5A, 5B, 5D, 7C, 8H (+ 6A-6I = NA)
- Steps 5A, 5B, 5D, 7C are NO for ALL channels (not channel-specific)
"""


def log_qa(question: str, response: str, mode: str = 'chat'):
    """save each Q&A pair for the learning loop"""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / 'qa_log.jsonl'
    entry = {
        'timestamp': datetime.now().isoformat(),
        'mode': mode,
        'question': question[:500],
        'response_preview': response[:300],
        'response_length': len(response),
    }
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to log Q&A: {e}")


class InsuranceAssistant:
    """hybrid AI assistant — rules engine for eval, RAG for retrieval, claude for reasoning"""

    def __init__(self):
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.model = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-6')
        self.max_tokens = int(os.getenv('CLAUDE_MAX_TOKENS', '8192'))
        self.documents = load_knowledge_base()

        # init RAG vector store
        self.vector_store = VectorStore()
        if self.vector_store.is_available():
            logger.info("RAG vector store loaded from cache")
        else:
            logger.info("Building RAG index from knowledge base...")
            self.vector_store.index_documents()

        # init claude client
        if not self.api_key or not self.api_key.startswith('sk-ant-'):
            logger.warning("ANTHROPIC_API_KEY not found — AI will not be available")
            self.client = None
        else:
            try:
                self.client = Anthropic(api_key=self.api_key)
                logger.info(f"Hybrid AI Assistant ready | model: {self.model} | "
                            f"docs: {len(self.documents)} | "
                            f"RAG chunks: {self.vector_store.collection.count() if self.vector_store.collection else 0}")
            except Exception as e:
                logger.error(f"Failed to init Anthropic client: {e}")
                self.client = None

    def reload_knowledge_base(self):
        """called after uploading/deleting docs — re-indexes RAG"""
        self.documents = load_knowledge_base()
        self.vector_store.index_documents()
        logger.info("Knowledge base and RAG index reloaded")

    def is_available(self) -> bool:
        return self.client is not None

    def _get_rag_context(self, query: str, top_k: int = 8) -> str:
        """retrieve relevant chunks from the vector store for this query"""
        chunks = self.vector_store.query(query, top_k=top_k)
        if not chunks:
            # fallback — load all txt files directly (like the old approach)
            return self._load_full_kb()

        context_parts = []
        for i, chunk in enumerate(chunks):
            context_parts.append(
                f"--- Retrieved Context [{i+1}] (source: {chunk['source']}) ---\n"
                f"{chunk['text']}"
            )
        return "\n\n".join(context_parts)

    def _load_full_kb(self) -> str:
        """fallback if RAG isn't available — loads everything like before"""
        files = sorted(KB_DIR.glob('*.txt'))
        sections = []
        for f in files:
            try:
                text = f.read_text(encoding='utf-8').strip()
                sections.append(f"DOCUMENT: {f.name}\n\n{text}")
            except Exception:
                pass
        return "\n\n".join(sections)

    def evaluate_with_rules_engine(self, case_data) -> dict:
        """run the deterministic rules engine on the case data"""
        try:
            if isinstance(case_data, str):
                try:
                    case_data = json.loads(case_data)
                except json.JSONDecodeError:
                    return None
            return evaluate_case(case_data)
        except Exception as e:
            logger.error(f"Rules engine error: {e}")
            return None

    def chat_stream(self, messages: list, mode: str = 'chat') -> Iterator[str]:
        """stream response — uses RAG for context and rules engine for evaluation"""
        if not self.client:
            yield ("**Configuration Error:** `ANTHROPIC_API_KEY` is not set or invalid. "
                   "Add a valid key to `backend/.env` and restart the server.\n\n"
                   "Get your key at: https://console.anthropic.com/")
            return

        # get the last user message for RAG retrieval
        user_msg = ''
        for m in reversed(messages):
            if m.get('role') == 'user':
                user_msg = m.get('content', '')
                break

        # retrieve relevant context via RAG (more chunks for broad Q&A questions)
        rag_context = self._get_rag_context(user_msg, top_k=12)

        # build system prompt with RAG context
        system_prompt = SYSTEM_PROMPT_BASE + f"\n\n## RELEVANT SOP CONTEXT\n\n{rag_context}"

        # trim conversation to avoid context overflow
        trimmed = _trim_messages(messages)

        try:
            full_response = ''
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=trimmed,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

            log_qa(user_msg, full_response, mode)

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error communicating with Claude API:** {str(e)}"

    def evaluate_stream(self, case_data, messages: list) -> Iterator[str]:
        """evaluate mode — runs rules engine first, then claude explains the results.
        this is the hybrid approach: deterministic checks + LLM explanation"""
        if not self.client:
            yield ("**Configuration Error:** `ANTHROPIC_API_KEY` is not set or invalid. "
                   "Add a valid key to `backend/.env` and restart the server.")
            return

        # step 1: run rules engine
        rules_result = self.evaluate_with_rules_engine(case_data)

        if rules_result and "error" not in rules_result:
            # step 2: privacy filter — sanitize before LLM
            pf = PrivacyFilter()
            sanitized_result = pf.sanitize_for_llm(rules_result)
            mask_log = pf.get_mask_log()
            if mask_log:
                logger.info(f"Privacy filter masked {len(mask_log)} PII items before LLM call")

            # step 3: get relevant SOP context via RAG — include failing steps for better retrieval
            failed_steps = ' '.join(s.get('step_id', '') for s in rules_result.get('steps', []) if s.get('status') == 'Fail')
            query = f"SOP evaluation {rules_result.get('channel', '')} {rules_result.get('cnt_type', '')} {failed_steps} case checks"
            rag_context = self._get_rag_context(query)

            # step 4: build prompt with SANITIZED rules engine output + RAG context
            system_prompt = SYSTEM_PROMPT_BASE + f"\n\n## RELEVANT SOP CONTEXT\n\n{rag_context}"

            eval_prompt = (
                "The **Rules Engine** has already evaluated this case deterministically. "
                "Your job is to explain the results clearly and provide actionable guidance.\n\n"
                f"## Rules Engine Output\n```json\n{json.dumps(sanitized_result, indent=2)}\n```\n\n"
                "Please present this as a clear, well-formatted evaluation report with:\n"
                "1. SOP Rule Evaluation table (explain each step)\n"
                "2. Overall Decision\n"
                "3. Ops Outcome (specific DotSphere/L400 actions)\n"
                "4. Automation Trigger\n"
                "5. Notes (skipped steps, knowledge gaps)\n\n"
                "Also include the structured JSON output at the end.\n\n"
                "IMPORTANT RULES FOR THIS RESPONSE:\n"
                "- Use the step descriptions EXACTLY as provided in the rules engine output and system prompt\n"
                "- For follow-up codes, use ONLY the definitions from the system prompt (CSL = Customer clarification required, etc.)\n"
                "- Do NOT expand abbreviations or invent alternative names for codes or steps\n"
                "- For skipped steps, use the descriptions from the system prompt and note whether they are skipped due to channel gating OR because they are NO for ALL channels\n"
                "- Step 5D is 'Update incorrect fields on L400' (NOT occupation/income check)\n"
            )

            # append the eval prompt to messages (trimmed)
            eval_messages = _trim_messages(messages) + [{'role': 'user', 'content': eval_prompt}]
        else:
            # rules engine couldn't parse it — fall back to full LLM evaluation
            rag_context = self._get_rag_context(str(case_data))
            system_prompt = SYSTEM_PROMPT_BASE + f"\n\n## RELEVANT SOP CONTEXT\n\n{rag_context}"

            eval_prompt = (
                "Evaluate the following case against SOP-NBIG-STP-001. "
                "Go through EVERY applicable step. Show Pass/Fail/Skip for each.\n\n"
                f"**Case Data:**\n```\n{json.dumps(case_data, indent=2) if isinstance(case_data, dict) else str(case_data)}\n```\n\n"
                "Provide the full 5-part evaluation format."
            )
            eval_messages = _trim_messages(messages) + [{'role': 'user', 'content': eval_prompt}]

        try:
            full_response = ''
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=eval_messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

            user_msg = str(case_data)[:500] if isinstance(case_data, dict) else str(case_data)[:500]
            log_qa(user_msg, full_response, 'evaluate')

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error communicating with Claude API:** {str(e)}"

    def email_draft_stream(self, email_data: dict, messages: list) -> Iterator[str]:
        """Use Case 2: generate empathetic customer email for UW decisions.
        AI communicates decisions — it does NOT make them."""
        if not self.client:
            yield "**Configuration Error:** API key not set."
            return

        decision_type = email_data.get('decision_type', 'Decline')
        customer_name = email_data.get('customer_name', '[Customer Name]')
        outcome_summary = email_data.get('outcome_summary', 'Unable to offer coverage at this time')
        tone = email_data.get('tone_required', 'Empathetic')

        rag_context = self._get_rag_context(
            f"email communication rules {decision_type} customer empathetic compliant", top_k=10)

        email_system = (
            "You are the **Singlife AI Customer Communication Assistant**.\n\n"
            "## Your Role\n"
            "You draft empathetic, compliant customer emails for underwriting decisions.\n"
            "The decision has ALREADY been made by the underwriter. You only COMMUNICATE it.\n\n"
            "## CRITICAL RULES — NON-NEGOTIABLE\n"
            "- NEVER disclose medical conditions, diagnoses, test names, ICD codes\n"
            "- NEVER reference internal UW logic, thresholds, systems (L400, DotSphere)\n"
            "- NEVER blame the customer or sound judgmental\n"
            "- NEVER use clinical or technical medical language\n"
            "- ALL emails are DRAFTS for human review — never auto-sent\n"
            "- Use general terms only: 'overall assessment', 'current guidelines'\n\n"
            "## Tone Requirements\n"
            f"- Decision Type: {decision_type}\n"
            f"- Required Tone: {tone}\n"
            "- Decline = Empathetic | Postpone = Reassuring | Counter-offer = Supportive\n\n"
            "## Output Format\n"
            "Produce TWO sections:\n"
            "### 1. Analysis (Internal — for ops review)\n"
            "- Decision context, tone assessment, guardrails check\n"
            "- Confirm: no medical disclosure, compliant language\n\n"
            "### 2. Customer Email Draft\n"
            "- Subject line\n"
            "- Full email body: Greeting → Acknowledgement → Decision → Reassurance → Next Steps → Support → Closing\n"
            "- Sign off: Warm regards, [Frontliner Name / Customer Service Team], [Company Name]\n\n"
            f"## RELEVANT CONTEXT\n\n{rag_context}"
        )

        # privacy filter — sanitize email data before LLM
        pf = PrivacyFilter()
        sanitized_email = pf.sanitize_for_llm(email_data)
        mask_log = pf.get_mask_log()
        if mask_log:
            logger.info(f"Privacy filter masked {len(mask_log)} PII items in email draft")

        safe_customer = sanitized_email.get('customer_name', customer_name)
        safe_extra = {k: v for k, v in sanitized_email.items() if k not in ('decision_type', 'customer_name', 'outcome_summary', 'tone_required')}

        user_prompt = (
            f"Generate a customer email for this underwriting decision:\n\n"
            f"**Decision Type:** {decision_type}\n"
            f"**Customer Name:** {safe_customer}\n"
            f"**Outcome Summary:** {outcome_summary}\n"
            f"**Tone:** {tone}\n"
            f"**Additional Context:** {json.dumps(safe_extra, indent=2)}\n\n"
            "Follow the email communication rules exactly. Produce the Analysis section first, then the full Customer Email Draft."
        )

        eval_messages = _trim_messages(messages) + [{'role': 'user', 'content': user_prompt}]

        try:
            full_response = ''
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=email_system,
                messages=eval_messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text
            log_qa(f"email_draft:{decision_type}", full_response, 'email')
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error:** {str(e)}"

    def _load_qa_scoring_config(self) -> dict:
        """load QA scoring rules from qa_scoring_rules.json"""
        config_path = KB_DIR / 'qa_scoring_rules.json'
        try:
            return json.loads(config_path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.error(f"Failed to load QA scoring config: {e}")
            return {}

    def _calculate_qa_score(self, qa_data: dict) -> dict:
        """Calculate QA complexity score — all thresholds, points, and risk levels
        read from qa_scoring_rules.json. Zero hardcoded business logic."""
        config = self._load_qa_scoring_config()
        if not config:
            return {"error": "QA scoring config not found", "complexity_score": 0, "risk_level": "Unknown"}

        icd_cnt = qa_data.get('icd_cnt', len(qa_data.get('icd_codes', [])))
        decision = qa_data.get('decision', '')

        # auto-detect sensitive ICD from config's sensitive code list
        sensitive = qa_data.get('sensitive_icd_flag', False)
        if not sensitive and qa_data.get('icd_codes'):
            sensitive_codes = set(config.get('sensitive_icd_codes', []))
            sensitive = any(c in sensitive_codes for c in qa_data['icd_codes'])

        breakdown = []
        score = 0

        # evaluate each scoring indicator from config
        for indicator in config.get('scoring_indicators', []):
            label = indicator['label']
            input_field = indicator['input_field']
            ind_type = indicator['type']

            if ind_type == 'range':
                value = qa_data.get(input_field, 0)
                if input_field == 'icd_cnt':
                    value = icd_cnt
                matched = False
                for r in indicator.get('ranges', []):
                    if r['min'] <= value <= r['max']:
                        pts = r['points']
                        score += pts
                        detail = r['detail_template'].replace('{value}', str(value))
                        breakdown.append((label, pts, detail))
                        matched = True
                        break
                if not matched:
                    breakdown.append((label, 0, str(value)))

            elif ind_type == 'boolean':
                value = qa_data.get(input_field, False)
                if input_field == 'sensitive_icd_flag':
                    value = sensitive
                if value:
                    pts = indicator['points_if_true']
                    score += pts
                    breakdown.append((label, pts, indicator['detail_if_true']))

            elif ind_type == 'threshold':
                value = qa_data.get(input_field, 0)
                threshold = indicator['threshold']
                op = indicator['operator']
                exceeded = False
                if op == '>' and value > threshold:
                    exceeded = True
                elif op == '<' and value < threshold:
                    exceeded = True
                elif op == '>=' and value >= threshold:
                    exceeded = True
                elif op == '<=' and value <= threshold:
                    exceeded = True
                if exceeded:
                    pts = indicator['points_if_exceeded']
                    score += pts
                    detail = indicator['detail_template'].replace('{value}', str(value))
                    breakdown.append((label, pts, detail))

        # check validation rule from config
        val_rule = config.get('validation_rule', {})
        if val_rule and decision.lower() in ('decline', 'postpone') and icd_cnt == 0:
            risk_level = val_rule['level']
            recommendation = val_rule['recommendation']
        else:
            # determine risk level from config thresholds (sorted high to low)
            risk_level = "Low"
            recommendation = "Standard review"
            for level in config.get('risk_levels', []):
                if score >= level['min_score']:
                    risk_level = level['level']
                    recommendation = level['recommendation']
                    break

        return {
            "complexity_score": score,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "breakdown": breakdown,
            "sensitive_icd_flag": sensitive,
        }

    def qa_review_stream(self, qa_data: dict, messages: list) -> Iterator[str]:
        """Use Case 3: QA review of underwriting results.
        AI summarises complexity and supports QA — does NOT override decisions."""
        if not self.client:
            yield "**Configuration Error:** API key not set."
            return

        # calculate score deterministically
        qa_score = self._calculate_qa_score(qa_data)

        rag_context = self._get_rag_context(
            "QA underwriting review scoring rules complexity indicators", top_k=10)

        qa_system = (
            "You are the **Singlife AI QA Review Assistant**.\n\n"
            "## Your Role\n"
            "You help QA reviewers understand and explain underwriting results.\n"
            "You do NOT approve, reject, or override any underwriting decision.\n\n"
            "## CRITICAL RULES\n"
            "- NEVER approve/reject/override UW decisions\n"
            "- NEVER make risk judgments or medical interpretations\n"
            "- NEVER introduce new assumptions\n"
            "- Organise information for reviewers, surface patterns, explain complexity\n\n"
            "## Output Format\n"
            "1. **QA Summary** — risk level, score, recommendation\n"
            "2. **Scoring Breakdown** — each rule applied with points\n"
            "3. **Risk Driver Analysis** — plain language explanation\n"
            "4. **Explainability Notes** — why this case needs attention\n\n"
            "Also include structured JSON at the end.\n\n"
            f"## RELEVANT CONTEXT\n\n{rag_context}"
        )

        # privacy filter — sanitize QA data before LLM
        pf = PrivacyFilter()
        sanitized_qa = pf.sanitize_for_llm(qa_data)
        mask_log = pf.get_mask_log()
        if mask_log:
            logger.info(f"Privacy filter masked {len(mask_log)} PII items in QA review")

        user_prompt = (
            f"Review this underwriting case for QA:\n\n"
            f"**Case Data:**\n```json\n{json.dumps(sanitized_qa, indent=2)}\n```\n\n"
            f"**Pre-calculated QA Score:**\n```json\n{json.dumps(qa_score, indent=2)}\n```\n\n"
            "Explain the QA scoring, highlight risk drivers, and provide a structured review."
        )

        eval_messages = _trim_messages(messages) + [{'role': 'user', 'content': user_prompt}]

        try:
            full_response = ''
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=qa_system,
                messages=eval_messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text
            log_qa(f"qa_review:{qa_data.get('case_id', 'unknown')}", full_response, 'qa_review')
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error:** {str(e)}"

    def get_qa_logs(self, limit: int = 50) -> List[Dict]:
        """read the jsonl log and return last N entries"""
        log_file = LOG_DIR / 'qa_log.jsonl'
        if not log_file.exists():
            return []
        entries = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read Q&A logs: {e}")
        return entries[-limit:]
