# claude_service.py — hybrid architecture: rules engine + RAG + LLM
# the rules engine handles deterministic SOP checks (from sop_rules.json)
# RAG retrieves relevant doc chunks (instead of stuffing everything in)
# claude just does the reasoning and explanation part
# NTU x Singlife veNTUre Sprint 2

import os
import json
import logging
import re
import fcntl
from pathlib import Path
from typing import Iterator, List, Dict, Optional
from datetime import datetime, timezone

from anthropic import Anthropic
from dotenv import load_dotenv

from services.rules_engine import evaluate_case
from services.rag_service import VectorStore, SUPPORTED_EXTENSIONS, extract_text
from services.privacy_filter import PrivacyFilter

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env', override=False)

logger = logging.getLogger(__name__)

KB_DIR = Path(__file__).parent.parent.parent / 'knowledge_base'
LOG_DIR = Path(__file__).parent.parent.parent / 'logs'


MAX_CONVERSATION_MESSAGES = int(os.getenv('MAX_CONVERSATION_MESSAGES', '20'))
MAX_MESSAGE_CHARS = int(os.getenv('MAX_MESSAGE_CHARS', '4000'))
MAX_FULL_SOURCE_CHARS = int(os.getenv('MAX_FULL_SOURCE_CHARS', '100000'))
MAX_CONTEXT_CHARS = int(os.getenv('MAX_CONTEXT_CHARS', '140000'))
MAX_SOURCES_PER_RESPONSE = int(os.getenv('MAX_SOURCES_PER_RESPONSE', '3'))
MAX_QA_LOG_LIMIT = int(os.getenv('MAX_QA_LOG_LIMIT', '10000'))
FILE_MATCH_CONFIDENCE_MIN = 0.72
FILE_MATCH_TIE_MARGIN = 0.03
EXPANDED_NEIGHBOR_WINDOW = 1


def _trim_messages(messages: list) -> list:
    """Keep conversation within context limits.
    Preserves the first message and last N messages."""
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


def load_knowledge_base() -> List[Dict]:
    """Scan knowledge_base/ for all supported file types and return
    metadata for the sidebar document list."""
    KB_DIR.mkdir(exist_ok=True)
    doc_info = []
    for f in sorted(KB_DIR.iterdir()):
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            ext = f.suffix.lower()
            if ext in ('.txt', '.json'):
                chars = len(f.read_text(encoding='utf-8').strip())
            else:
                chars = f.stat().st_size
            doc_info.append({
                'name': f.stem.replace('_', ' ').title(),
                'filename': f.name,
                'chars': chars,
                'type': ext.lstrip('.'),
            })
        except Exception as e:
            logger.error(f"Failed to read {f.name}: {e}")
    return doc_info


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
- Use the **Retrieval Context Header** to determine whether the provided content scope is full or partial

## Critical Rules — ANTI-HALLUCINATION
- NEVER guess or use external knowledge
- NEVER fix data autonomously — flag mismatches, humans decide
- Always cite Step IDs for traceability
- Use plan codes (EYA, EYB) not plan names
- If a rule/threshold is missing — flag as Knowledge Gap, do NOT guess
- NEVER expand abbreviations or invent definitions for follow-up codes or step descriptions
- Use ONLY the exact definitions from the context provided. If a definition is not in the context, say "definition not in retrieved context" rather than guessing.
- If `content_scope` is `full`, do NOT claim you lack access to the full file

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


def log_qa(question: str, response: str, mode: str = 'chat', retrieval_meta: Optional[Dict] = None):
    """Save each Q&A pair for the learning loop.
    Uses UTC timestamps (consistent with audit_log) and fcntl locking to prevent
    interleaved writes from concurrent gunicorn workers."""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / 'qa_log.jsonl'
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'mode': mode,
        'question': question[:500],
        'response_preview': response[:300],
        'response_length': len(response),
    }
    if retrieval_meta:
        entry['retrieval'] = retrieval_meta
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(json.dumps(entry) + '\n')
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"Failed to log Q&A: {e}")


class InsuranceAssistant:
    """hybrid AI assistant — rules engine for eval, RAG for retrieval, claude for reasoning"""

    def __init__(self):
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.model = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-6')
        # tolerate bad CLAUDE_MAX_TOKENS env values instead of crashing at startup
        try:
            self.max_tokens = int(os.getenv('CLAUDE_MAX_TOKENS', '8192'))
            if self.max_tokens <= 0:
                raise ValueError("must be positive")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid CLAUDE_MAX_TOKENS env value, defaulting to 8192: {e}")
            self.max_tokens = 8192
        self.documents = load_knowledge_base()

        # init RAG vector store — always runs incremental index to pick up
        # new/changed/deleted files since last startup
        self.vector_store = VectorStore()
        logger.info("Running incremental KB index...")
        self.vector_store.index_documents()

        # init claude client + validate key with a live API call
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set — AI will not be available")
            self.client = None
        elif not self.api_key.startswith('sk-ant-'):
            logger.warning("ANTHROPIC_API_KEY has wrong format (should start with sk-ant-) — AI will not be available")
            self.client = None
        else:
            try:
                self.client = Anthropic(api_key=self.api_key)
                self._validate_api_key()
                logger.info(f"Hybrid AI Assistant ready | model: {self.model} | "
                            f"docs: {len(self.documents)} | "
                            f"RAG chunks: {self.vector_store.collection.count() if self.vector_store.collection else 0}")
            except Exception as e:
                logger.error(f"Failed to init Anthropic client: {e}")
                self.client = None

    def _validate_api_key(self):
        """Make a lightweight API call to verify the key actually works.
        Uses models.list (no token cost). Falls back to a 1-token message
        if the SDK version doesn't support models.list."""
        try:
            self.client.models.list(limit=1)
            logger.info("API key validated successfully")
            return
        except AttributeError:
            pass
        except Exception as e:
            error_type = type(e).__name__
            if 'authentication' in error_type.lower() or 'auth' in str(e).lower():
                logger.error(f"API key is invalid or expired: {e}")
                self.client = None
                return
            if 'permission' in str(e).lower():
                logger.warning(f"models.list not permitted, trying fallback: {e}")
            else:
                raise

        try:
            self.client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            logger.info("API key validated successfully (via messages fallback)")
        except Exception as e:
            error_str = f"{type(e).__name__}: {e}"
            if 'authentication' in error_str.lower() or 'invalid' in error_str.lower():
                logger.error(f"API key is invalid or expired: {error_str}")
                self.client = None
            elif 'not_found' in error_str.lower() or 'model' in error_str.lower():
                logger.warning(f"Model '{self.model}' may not be available, but key is valid: {error_str}")
            else:
                logger.error(f"API key validation failed: {error_str}")
                self.client = None

    def reload_knowledge_base(self):
        """called after uploading/deleting docs — re-indexes RAG"""
        self.documents = load_knowledge_base()
        self.vector_store.index_documents()
        logger.info("Knowledge base and RAG index reloaded")

    def is_available(self) -> bool:
        return self.client is not None

    def _detect_explicit_filename_intent(self, query: str) -> bool:
        """Detect explicit user requests to read a specific file/document."""
        q = (query or "").strip().lower()
        if not q:
            return False
        if re.search(r"`[^`]+\.(txt|pdf|xlsx|json)`", q):
            return True
        if re.search(r"\b[\w\-]+\.(txt|pdf|xlsx|json)\b", q):
            return True
        intent_words = (
            "read file",
            "open file",
            "full file",
            "entire file",
            "entire document",
            "full document",
            "summarise",
            "summarize",
        )
        return any(word in q for word in intent_words) and ("file" in q or "document" in q)

    def _classify_query_type(self, query: str) -> str:
        q = (query or "").lower()
        if self._detect_explicit_filename_intent(q):
            return "explicit_file"
        broad_words = ("all", "entire", "full", "complete", "summarise", "summarize", "overview")
        if any(w in q for w in broad_words):
            return "broad"
        return "narrow"

    def _dynamic_top_k(self, query: str, base_top_k: int) -> int:
        q = (query or "").lower()
        if any(word in q for word in ("full", "entire", "all", "overview", "summarise", "summarize")):
            return max(base_top_k, 14)
        return base_top_k

    def _truncate_context_text(self, text: str, max_chars: int, label: str) -> tuple[str, Optional[str]]:
        if len(text) <= max_chars:
            return text, None
        truncated = text[:max_chars].rstrip()
        reason = f"trimmed_{label}_to_{max_chars}_chars"
        truncated += (
            f"\n\n[Context truncated: {label} exceeded budget. "
            "Ask 'continue' to review remaining sections.]"
        )
        return truncated, reason

    def _build_context_header(
        self,
        retrieval_mode: str,
        sources: List[str],
        content_scope: str,
        truncation: Optional[str],
        coverage_hint: str,
    ) -> str:
        return (
            "## RETRIEVAL CONTEXT HEADER\n"
            f"- retrieval_mode: {retrieval_mode}\n"
            f"- sources: {', '.join(sources) if sources else 'none'}\n"
            f"- coverage_hint: {coverage_hint}\n"
            f"- content_scope: {content_scope}\n"
            f"- truncation: {truncation or 'none'}"
        )

    def _build_clarification_message(self, candidates: List[str]) -> str:
        options = "\n".join([f"- `{name}`" for name in candidates[:5]])
        return (
            "I found multiple matching files and need you to pick one before I continue:\n\n"
            f"{options}\n\n"
            "Reply with the exact filename you want."
        )

    def _format_expanded_context(self, expanded_payload: dict) -> str:
        chunks = expanded_payload.get("chunks", [])
        if not chunks:
            return ""

        sources_seen = []
        lines = []
        for chunk in chunks:
            source = chunk.get("source", "unknown")
            if source not in sources_seen:
                sources_seen.append(source)
            if len(sources_seen) > MAX_SOURCES_PER_RESPONSE and source not in sources_seen[:MAX_SOURCES_PER_RESPONSE]:
                continue
            idx = chunk.get("chunk_index")
            marker = "matched" if chunk.get("is_match") else "neighbor"
            lines.append(
                f"--- Retrieved Context (source: {source}, chunk: {idx}, role: {marker}) ---\n"
                f"{chunk.get('text', '')}"
            )
        return "\n\n".join(lines)

    def _assess_context_quality(self, payload: dict) -> dict:
        quality = payload.get("quality", {}) if payload else {}
        if not quality:
            return {"sufficient": False, "reason": "missing_quality", "score": 0.0}
        result_count = int(quality.get("result_count", 0))
        best_score = quality.get("best_score")
        unique_sources = int(quality.get("unique_sources", 0))
        sufficient = bool(quality.get("sufficient", False))
        reason = quality.get("reason", "unknown")
        score = float(result_count)
        if best_score is not None:
            score += max(0.0, 2.0 - float(best_score))
        score -= max(0, unique_sources - 3) * 0.2
        return {
            "sufficient": sufficient,
            "reason": reason,
            "score": round(score, 3),
        }

    def _build_full_source_payload(self, source: str, retrieval_mode: str, fallback_reason: Optional[str] = None) -> dict:
        source_payload = self.vector_store.get_full_source_text(source)
        source_text = source_payload.get("text", "")
        if not source_text:
            return {
                "retrieval_mode": retrieval_mode,
                "query_type": "narrow",
                "sources": [source],
                "content_scope": "partial",
                "truncation": "source_extraction_failed",
                "coverage_hint": "full_source_unavailable",
                "context_text": "",
                "quality": {"sufficient": False, "reason": "source_extraction_failed", "score": 0.0},
                "fallback_reason": fallback_reason,
            }

        truncated_text, truncation = self._truncate_context_text(source_text, MAX_FULL_SOURCE_CHARS, "full_source")
        scope = "partial" if truncation else "full"
        coverage_hint = f"full_source ({len(truncated_text):,} chars loaded)"
        header = self._build_context_header(
            retrieval_mode=retrieval_mode,
            sources=[source],
            content_scope=scope,
            truncation=truncation,
            coverage_hint=coverage_hint,
        )
        return {
            "retrieval_mode": retrieval_mode,
            "query_type": "explicit_file" if retrieval_mode == "full_named_file" else "narrow",
            "sources": [source],
            "content_scope": scope,
            "truncation": truncation,
            "coverage_hint": coverage_hint,
            "context_text": f"{header}\n\n## SOURCE CONTENT ({source})\n\n{truncated_text}",
            "quality": {"sufficient": True, "reason": "full_source_loaded", "score": 1.0},
            "fallback_reason": fallback_reason,
        }

    def _prepare_retrieval_context(self, query: str, top_k: int = 8, prefer_full_named_file: bool = False) -> dict:
        query = (query or "").strip()
        query_type = self._classify_query_type(query)
        explicit_intent = self._detect_explicit_filename_intent(query)

        # Named-file mode
        if explicit_intent and prefer_full_named_file:
            name_match = self.vector_store.resolve_source_by_name(
                query,
                confidence_min=FILE_MATCH_CONFIDENCE_MIN,
                tie_margin=FILE_MATCH_TIE_MARGIN,
            )
            if name_match.get("ambiguous"):
                candidates = name_match.get("candidates", [])
                return {
                    "retrieval_mode": "clarification",
                    "query_type": query_type,
                    "sources": candidates,
                    "content_scope": "partial",
                    "truncation": None,
                    "coverage_hint": "ambiguous_filename_match",
                    "context_text": "",
                    "quality": {"sufficient": False, "reason": "ambiguous_filename_match", "score": 0.0},
                    "clarification_message": self._build_clarification_message(candidates),
                    "match_confidence": name_match.get("confidence"),
                }
            if name_match.get("matched"):
                full_payload = self._build_full_source_payload(
                    source=name_match["source"],
                    retrieval_mode="full_named_file",
                )
                full_payload["query_type"] = query_type
                full_payload["match_confidence"] = name_match.get("confidence")
                return full_payload

        # Semantic retrieval with optional priority source
        priority_sources = None
        name_match = self.vector_store.resolve_source_by_name(
            query,
            confidence_min=max(FILE_MATCH_CONFIDENCE_MIN, 0.80),
            tie_margin=FILE_MATCH_TIE_MARGIN,
        )
        if name_match.get("matched"):
            priority_sources = [name_match["source"]]

        tuned_top_k = self._dynamic_top_k(query, top_k)
        expanded_payload = self.vector_store.get_expanded_context(
            question=query,
            top_k=tuned_top_k,
            priority_sources=priority_sources,
            neighbor_window=EXPANDED_NEIGHBOR_WINDOW,
        )
        quality = self._assess_context_quality(expanded_payload)
        sources = list((expanded_payload.get("grouped_by_source") or {}).keys())
        coverage = expanded_payload.get("coverage", {})
        coverage_hint = ", ".join(
            [
                f"{src}:{meta.get('expanded_chunks', 0)}/{meta.get('total_chunks', 0)}"
                for src, meta in list(coverage.items())[:MAX_SOURCES_PER_RESPONSE]
            ]
        ) or "no_source_coverage"
        raw_context = self._format_expanded_context(expanded_payload)

        if raw_context:
            raw_context, context_truncation = self._truncate_context_text(raw_context, MAX_CONTEXT_CHARS, "retrieval_context")
        else:
            context_truncation = None

        if raw_context and quality.get("sufficient"):
            mode = "expanded" if any(c.get("is_match") is False for c in expanded_payload.get("chunks", [])) else "semantic"
            header = self._build_context_header(
                retrieval_mode=mode,
                sources=sources[:MAX_SOURCES_PER_RESPONSE],
                content_scope="partial" if context_truncation else "full",
                truncation=context_truncation,
                coverage_hint=coverage_hint,
            )
            return {
                "retrieval_mode": mode,
                "query_type": query_type,
                "sources": sources[:MAX_SOURCES_PER_RESPONSE],
                "content_scope": "partial" if context_truncation else "full",
                "truncation": context_truncation,
                "coverage_hint": coverage_hint,
                "context_text": f"{header}\n\n## RETRIEVED EXCERPTS\n\n{raw_context}",
                "quality": quality,
                "match_confidence": name_match.get("confidence"),
            }

        # Insufficient coverage fallback — load full top source if available
        fallback_source = sources[0] if sources else (priority_sources[0] if priority_sources else None)
        if fallback_source:
            fallback_payload = self._build_full_source_payload(
                source=fallback_source,
                retrieval_mode="full_fallback",
                fallback_reason=quality.get("reason"),
            )
            fallback_payload["query_type"] = query_type
            fallback_payload["match_confidence"] = name_match.get("confidence")
            fallback_payload["quality"] = quality
            return fallback_payload

        # Last resort fallback to full KB
        full_kb = self._load_full_kb()
        full_kb, kb_truncation = self._truncate_context_text(full_kb, MAX_CONTEXT_CHARS, "full_kb")
        header = self._build_context_header(
            retrieval_mode="full_kb_fallback",
            sources=[],
            content_scope="partial" if kb_truncation else "full",
            truncation=kb_truncation,
            coverage_hint="full_kb_concat_fallback",
        )
        return {
            "retrieval_mode": "full_kb_fallback",
            "query_type": query_type,
            "sources": [],
            "content_scope": "partial" if kb_truncation else "full",
            "truncation": kb_truncation,
            "coverage_hint": "full_kb_concat_fallback",
            "context_text": f"{header}\n\n{full_kb}",
            "quality": quality,
            "match_confidence": name_match.get("confidence"),
        }

    def _log_retrieval_telemetry(self, query: str, payload: dict):
        logger.info(
            "retrieval | query_type=%s | mode=%s | sources=%s | scope=%s | truncation=%s | quality=%s | score=%s",
            payload.get("query_type"),
            payload.get("retrieval_mode"),
            ",".join(payload.get("sources", [])) if payload.get("sources") else "none",
            payload.get("content_scope"),
            payload.get("truncation") or "none",
            payload.get("quality", {}).get("reason"),
            payload.get("quality", {}).get("score"),
        )

    def _get_rag_context(self, query: str, top_k: int = 8) -> str:
        """Compatibility wrapper around structured retrieval context."""
        payload = self._prepare_retrieval_context(query, top_k=top_k, prefer_full_named_file=False)
        return payload.get("context_text", "")

    def _load_full_kb(self) -> str:
        """Fallback if RAG isn't available — extract text from all
        supported KB files and concatenate."""
        sections = []
        for f in sorted(KB_DIR.iterdir()):
            if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            text = extract_text(f)
            if text:
                sections.append(f"DOCUMENT: {f.name}\n\n{text}")
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

    def _build_local_attachments_context(self, local_attachments: List[Dict] | None) -> str:
        if not local_attachments:
            return ""
        sections = []
        for i, item in enumerate(local_attachments, start=1):
            filename = item.get('filename', f'attachment_{i}')
            filetype = item.get('filetype', 'txt')
            text = item.get('text', '')
            if text:
                sections.append(
                    f"--- Chat Attachment [{i}] ({filename}, type={filetype}) ---\n{text}"
                )
        if not sections:
            return ""
        return (
            "## CHAT-LOCAL ATTACHMENTS (conversation-only)\n\n"
            "Use these attachments as highest-priority context for this chat. "
            "If chat-local content conflicts with global KB context, prefer chat-local content.\n\n"
            + "\n\n".join(sections)
        )

    def chat_stream(self, messages: list, mode: str = 'chat', local_attachments: List[Dict] | None = None) -> Iterator[str]:
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

        pf = PrivacyFilter()

        # retrieve context via intent-aware strategy (named-file/full/expanded/fallback)
        retrieval_payload = self._prepare_retrieval_context(
            user_msg,
            top_k=12,
            prefer_full_named_file=True,
        )
        self._log_retrieval_telemetry(user_msg, retrieval_payload)
        if retrieval_payload.get("retrieval_mode") == "clarification":
            clarification = retrieval_payload.get("clarification_message", "Please clarify which file you want.")
            yield clarification
            log_qa(pf.sanitize_text(user_msg), clarification, mode, retrieval_meta=retrieval_payload)
            return

        rag_context = retrieval_payload.get("context_text", "")
        local_context = self._build_local_attachments_context(local_attachments)

        # mask PII in local attachment content and conversation messages before sending to Anthropic
        sanitized_local = pf.sanitize_text(local_context) if local_context else local_context
        trimmed = _trim_messages(messages)
        masked_messages = pf.sanitize_for_llm(trimmed)

        # build system prompt with RAG context
        system_prompt = SYSTEM_PROMPT_BASE
        if sanitized_local:
            system_prompt += f"\n\n{sanitized_local}"
        system_prompt += f"\n\n## RELEVANT SOP CONTEXT\n\n{rag_context}"

        try:
            full_response = ''
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=masked_messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

            log_qa(pf.sanitize_text(user_msg), full_response, mode, retrieval_meta=retrieval_payload)

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

            # step 3: get relevant SOP context via RAG — include failing steps for better retrieval.
            # bug fix: read from 'sop_rule_evaluation' (the actual key) not 'steps'.
            # also include any non-Pass status (Refer UW / Refer Ops / Manual Review) for richer queries.
            non_pass = [
                s.get('step_id', '')
                for s in rules_result.get('sop_rule_evaluation', [])
                if s.get('status') and s.get('status') != 'Pass' and s.get('status') != 'Skip'
            ]
            failed_steps = ' '.join(filter(None, non_pass))
            query = f"SOP evaluation {rules_result.get('channel', '')} {rules_result.get('cnt_type', '')} {failed_steps} case checks"
            retrieval_payload = self._prepare_retrieval_context(query, top_k=10, prefer_full_named_file=False)
            self._log_retrieval_telemetry(query, retrieval_payload)
            rag_context = retrieval_payload.get("context_text", "")

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
                "- For follow-up codes, use ONLY the definitions from the system prompt (for example: CSL = Basic CSL Plan Status check)\n"
                "- Do NOT expand abbreviations or invent alternative names for codes or steps\n"
                "- For skipped steps, use the descriptions from the system prompt and note whether they are skipped due to channel gating OR because they are NO for ALL channels\n"
                "- Step 5D is 'Update incorrect fields on L400' (NOT occupation/income check)\n"
            )

            # append the eval prompt to messages (trimmed)
            eval_messages = _trim_messages(messages) + [{'role': 'user', 'content': eval_prompt}]
        else:
            # rules engine couldn't parse it — fall back to full LLM evaluation
            pf = PrivacyFilter()
            sanitized_case = pf.sanitize_for_llm(case_data)
            # use SANITIZED case for the fallback RAG query — the query string is logged
            # via _log_retrieval_telemetry, so passing raw case_data would leak PII
            fallback_query = str(sanitized_case)
            retrieval_payload = self._prepare_retrieval_context(fallback_query, top_k=10, prefer_full_named_file=False)
            self._log_retrieval_telemetry(fallback_query, retrieval_payload)
            rag_context = retrieval_payload.get("context_text", "")
            system_prompt = SYSTEM_PROMPT_BASE + f"\n\n## RELEVANT SOP CONTEXT\n\n{rag_context}"

            eval_prompt = (
                "Evaluate the following case against SOP-NBIG-STP-001. "
                "Go through EVERY applicable step. Show Pass/Fail/Skip for each.\n\n"
                f"**Case Data:**\n```\n{json.dumps(sanitized_case, indent=2) if isinstance(sanitized_case, dict) else str(sanitized_case)}\n```\n\n"
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

            # reuse the already-populated `pf` so its mask log is consistent across this request
            user_msg = str(pf.sanitize_for_llm(case_data))[:500]
            log_qa(user_msg, full_response, 'evaluate', retrieval_meta=retrieval_payload)

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error communicating with Claude API:** {str(e)}"

    def email_draft_stream(self, email_data: dict, messages: list) -> Iterator[str]:
        """Use Case 2: generate empathetic customer email for UW decisions.
        AI communicates decisions — it does NOT make them."""
        if not self.client:
            yield "**Configuration Error:** API key not set."
            return

        decision_type = email_data.get('decision_type', 'Review Required')
        customer_name = email_data.get('customer_name', '[Customer Name]')
        outcome_summary = email_data.get('outcome_summary', 'Your application is currently under review.')
        tone = email_data.get('tone_required', 'Reassuring')

        email_query = f"email communication rules {decision_type} customer empathetic compliant"
        retrieval_payload = self._prepare_retrieval_context(email_query, top_k=10, prefer_full_named_file=False)
        self._log_retrieval_telemetry(email_query, retrieval_payload)
        rag_context = retrieval_payload.get("context_text", "")

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
            log_qa(f"email_draft:{decision_type}", full_response, 'email', retrieval_meta=retrieval_payload)
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
        read from qa_scoring_rules.json. Zero hardcoded business logic.

        Accepts both flat and nested payloads:
          flat:   {"icd_cnt": 4, "decision": "Postpone", ...}
          nested: {"case_metadata": {"decision": "Postpone"},
                   "qa_indicators": {"icd_cnt": 4, ...}}
        """
        config = self._load_qa_scoring_config()
        if not config:
            return {"error": "QA scoring config not found", "complexity_score": 0, "risk_level": "Unknown"}

        # flatten nested payload (per AI_Brain_QA_Sample_*.json spec format)
        # falls back to top-level for backward compatibility
        indicators = qa_data.get('qa_indicators', {})
        metadata = qa_data.get('case_metadata', {})
        def g(key, default=None):
            if key in qa_data:
                return qa_data[key]
            if key in indicators:
                return indicators[key]
            if key in metadata:
                return metadata[key]
            return default

        icd_codes = g('icd_codes', [])
        icd_cnt = g('icd_cnt', len(icd_codes) if icd_codes else 0)
        decision = g('decision', '')

        # auto-detect sensitive ICD from config's sensitive code list
        sensitive = g('sensitive_icd_flag', False)
        if not sensitive and icd_codes:
            sensitive_codes = set(config.get('sensitive_icd_codes', []))
            # filter out None / non-string entries to avoid TypeError on `c in set`
            sensitive = any(c in sensitive_codes for c in icd_codes if isinstance(c, str))

        breakdown = []
        score = 0

        # evaluate each scoring indicator from config
        for indicator in config.get('scoring_indicators', []):
            label = indicator['label']
            input_field = indicator['input_field']
            ind_type = indicator['type']

            if ind_type == 'range':
                value = g(input_field, 0)
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
                value = g(input_field, False)
                if input_field == 'sensitive_icd_flag':
                    value = sensitive
                if value:
                    pts = indicator['points_if_true']
                    score += pts
                    breakdown.append((label, pts, indicator['detail_if_true']))

            elif ind_type == 'threshold':
                value = g(input_field, 0)
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

        qa_query = "QA underwriting review scoring rules complexity indicators"
        retrieval_payload = self._prepare_retrieval_context(qa_query, top_k=10, prefer_full_named_file=False)
        self._log_retrieval_telemetry(qa_query, retrieval_payload)
        rag_context = retrieval_payload.get("context_text", "")

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
            log_qa(
                f"qa_review:{qa_data.get('case_id', 'unknown')}",
                full_response,
                'qa_review',
                retrieval_meta=retrieval_payload,
            )
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error:** {str(e)}"

    def get_qa_logs(self, limit: int = 50) -> List[Dict]:
        """Read the jsonl log and return last N entries.
        Caps limit at MAX_QA_LOG_LIMIT to protect memory.
        Skips corrupt JSON lines (same robustness as audit_log P0-2 fix)."""
        # cap limit so a hostile ?limit=99999999 doesn't OOM the server
        limit = max(1, min(int(limit) if limit else 50, MAX_QA_LOG_LIMIT))
        log_file = LOG_DIR / 'qa_log.jsonl'
        if not log_file.exists():
            return []
        entries = []
        skipped = 0
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        skipped += 1
                        logger.warning(f"Skipping corrupt qa_log line {line_num}: {e}")
        except Exception as e:
            logger.error(f"Failed to read Q&A logs: {e}")
        if skipped:
            logger.info(f"qa_log read: {len(entries)} valid, {skipped} corrupt skipped")
        return entries[-limit:]
