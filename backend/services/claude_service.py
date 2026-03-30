# claude_service.py
# this is the core of the AI side — loads our SOP docs, builds the prompt,
# calls claude and streams back responses. also logs every Q&A for the
# learning loop (US2.4 in our user stories)

import os
import json
import logging
from pathlib import Path
from typing import Iterator, List, Dict
from datetime import datetime

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env', override=True)

logger = logging.getLogger(__name__)

# knowledge_base/ is at project root, this file is in backend/services/
KB_DIR = Path(__file__).parent.parent.parent / 'knowledge_base'
LOG_DIR = Path(__file__).parent.parent.parent / 'logs'


def load_knowledge_base() -> tuple[str, List[Dict]]:
    """grab all .txt files from knowledge_base/ and mash them into one big
    context string. this gets stuffed into the system prompt so claude
    can reference our SOPs when answering questions"""
    KB_DIR.mkdir(exist_ok=True)

    files = sorted(KB_DIR.glob('*.txt'))
    if not files:
        logger.warning(f"No .txt files found in {KB_DIR}")
        return "(No documents found in knowledge_base/ directory.)", []

    sections = []
    doc_info = []
    for f in files:
        try:
            text = f.read_text(encoding='utf-8').strip()
            sections.append(
                f"{'=' * 80}\n"
                f"DOCUMENT: {f.name}\n"
                f"{'=' * 80}\n\n"
                f"{text}"
            )
            doc_info.append({
                'name': f.stem.replace('_', ' ').title(),
                'filename': f.name,
                'chars': len(text),
            })
            logger.info(f"Loaded knowledge base file: {f.name} ({len(text):,} chars)")
        except Exception as e:
            logger.error(f"Failed to load {f.name}: {e}")

    combined = "\n\n\n".join(sections)
    logger.info(
        f"Knowledge base ready: {len(files)} document(s), "
        f"{len(combined):,} total chars"
    )
    return combined, doc_info


def build_system_prompt(knowledge_base: str) -> str:
    """constructs the system prompt that defines how the AI behaves.
    three modes: SOP evaluation, general Q&A, and knowledge gap detection.
    spent quite a bit of time tuning this to get the output format right"""
    return f"""You are the **Singlife AI Operations Assistant** — an intelligent operations copilot for insurance professionals.

## Your Capabilities

### Mode 1: SOP Case Evaluation
When given case data (policy number, client fields, L400 data, follow-up codes, underwriting indicators), you MUST:
1. Identify the applicable SOP (e.g., SOP-NBIG-STP-001 for New Business pre-issue checks)
2. Determine the submission channel (QnB, EzSub, or Hardcopy) from the data
3. Evaluate the case against EACH applicable SOP step
4. Show Pass / Fail / Manual Review / Not Applicable for each step
5. Derive the overall decision based on SOP outcomes
6. Output in this EXACT format:

**1. SOP Rule Evaluation**
For each applicable step, show:
- Step ID and description
- Data compared (what was checked)
- Result: Pass / Fail / Refer Ops / Refer UW / Skip
- Confidence: High / Medium / Low
- Reason (brief)
IMPORTANT: If a step's channel flag = N for the current channel, mark it as "Skip" — do NOT evaluate it as Pass or Fail.

**2. Overall Decision**
One of: Standard | Standard with Further Requirements | Refer to UW | Trigger GNS Review | Trigger Compliance | Withdrawal

**3. Ops Outcome**
What the processor should do next — clear, actionable instruction.

**4. Automation Trigger**
Yes or No

**5. Notes**
- Which steps were skipped and why (channel gating)
- Any knowledge gaps found
- Any assumptions made

Also output structured JSON:
```json
{{
  "channel": "...",
  "sop_rule_evaluation": [
    {{"step_id": "...", "status": "...", "finding": "...", "confidence": "..."}}
  ],
  "overall_decision": "...",
  "ops_outcome": "...",
  "automation_trigger": "Yes/No",
  "notes": ["..."]
}}
```

### Mode 2: General Q&A
When asked questions about SOPs, policies, or processes:
- Use ONLY content from the knowledge base below
- Always cite the specific SOP step, section, or document
- Follow format: Summary → Steps → Exceptions → References
- If the answer is not in the knowledge base, say so explicitly — do NOT guess
- If the question is ambiguous, ask clarifying questions

### Mode 3: Knowledge Gap Detection
When you cannot answer confidently or find missing/unclear rules:
- Clearly state what information is missing
- Reference the SOP step where the gap exists
- Suggest what clarification is needed
- Format as:
  * **Question:** (what was asked)
  * **SOP Reference:** (which step)
  * **Gap:** (what's missing)
  * **Suggested Clarification:** (what to ask the SME)

## Critical Rules
- **Channel gating is mandatory** — if a step's channel flag = N, SKIP it entirely (do not evaluate as Pass/Fail)
- **NEVER guess or use external knowledge** — only use the loaded documents
- **NEVER autonomously fix data** — flag mismatches, recommend actions, but humans decide
- **Always explain your reasoning** — cite the Step IDs that led to the decision (traceability)
- **Use plan codes (e.g., EYA, EYB) not plan names** — codes are stable, names vary
- **Follow-up codes are key signals** — F45=Premium mismatch, C09=GNS re-screening, CSL=Clarification required
- **Critical fields require human verification** — DOB, Gender, NRIC, Nationality mismatches must be flagged, not resolved by AI
- **If a rule/threshold is missing or unclear** — flag a Knowledge Gap, do NOT guess

---

## KNOWLEDGE BASE — LOADED DOCUMENTS

{knowledge_base}
"""


def log_qa(question: str, response: str, mode: str = 'chat'):
    """save each Q&A pair to a jsonl file. we review these to find
    recurring questions and spot where the AI struggles (knowledge gaps)"""
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
    """wraps the anthropic client + knowledge base. handles streaming
    responses for both chat and case evaluation modes"""

    def __init__(self):
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.model = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-6')
        self.max_tokens = int(os.getenv('CLAUDE_MAX_TOKENS', '4096'))
        self.knowledge_base, self.documents = load_knowledge_base()
        self.system_prompt = build_system_prompt(self.knowledge_base)

        if not self.api_key or not self.api_key.startswith('sk-ant-'):
            logger.warning(
                "Valid ANTHROPIC_API_KEY not found — AI assistant will not be available. "
                "Set it in backend/.env"
            )
            self.client = None
        else:
            try:
                self.client = Anthropic(api_key=self.api_key)
                logger.info(
                    f"Singlife AI Assistant initialised | model: {self.model} | "
                    f"knowledge base: {len(self.knowledge_base):,} chars"
                )
            except Exception as e:
                logger.error(f"Failed to initialise Anthropic client: {e}")
                self.client = None

    def reload_knowledge_base(self):
        """called after uploading/deleting docs so the prompt picks up changes"""
        self.knowledge_base, self.documents = load_knowledge_base()
        self.system_prompt = build_system_prompt(self.knowledge_base)
        logger.info("Knowledge base reloaded")

    def is_available(self) -> bool:
        return self.client is not None

    def chat_stream(self, messages: list, mode: str = 'chat') -> Iterator[str]:
        """stream response chunks back one at a time. works for both chat
        and evaluate modes. logs the full exchange after streaming finishes"""
        if not self.client:
            yield (
                "**Configuration Error:** `ANTHROPIC_API_KEY` is not set or invalid. "
                "Add a valid key to `backend/.env` and restart the server.\n\n"
                "Get your key at: https://console.anthropic.com/"
            )
            return

        try:
            full_response = ''
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

            # find the last user message so we can log it
            user_msg = ''
            for m in reversed(messages):
                if m.get('role') == 'user':
                    user_msg = m.get('content', '')
                    break
            log_qa(user_msg, full_response, mode)

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error communicating with Claude API:** {str(e)}"

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
