"""
Singlife AI Assistant — Insurance Knowledge Engine
Claude-powered intelligent assistant grounded in uploaded documents.

Knowledge base is loaded dynamically from the knowledge_base/ directory at the
project root. Documents can be uploaded via the UI or dropped as .txt files.
"""

import os
import logging
from pathlib import Path
from typing import Iterator, List, Dict

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env', override=True)

logger = logging.getLogger(__name__)

# ─── Knowledge base loader ────────────────────────────────────────────────────

# knowledge_base/ lives two levels up from here (backend/services/ → root)
KB_DIR = Path(__file__).parent.parent.parent / 'knowledge_base'


def load_knowledge_base() -> tuple[str, List[Dict]]:
    """
    Load every .txt file in knowledge_base/ and combine them into one
    knowledge string that is injected into the Claude system prompt.
    Returns (combined_text, list_of_doc_info).
    """
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
    return f"""You are the **Singlife AI Assistant** — an intelligent document analysis engine designed for insurance professionals (underwriters, claims adjusters, brokers, and agents).

## Your Role
You serve as an intelligent copilot grounded exclusively in the documents loaded into your knowledge base. You help with:
- **Policy coverage interpretation** — precise answers with specific section references
- **Claims adjudication support** — what is and isn't covered, claims procedures, required documentation
- **Exclusion analysis** — proactively surfacing relevant exclusions for any coverage question
- **Regulatory compliance guidance** — jurisdiction-specific requirements
- **Underwriting intelligence** — sub-limits, waiting periods, eligibility requirements, under-insurance calculations
- **General document Q&A** — answering any question grounded in the uploaded documents

## Response Guidelines
1. **Always cite specific sections** from the documents — professionals need precise references.
2. **State exact amounts** as documented (e.g., S$ for Singapore policies).
3. **Proactively flag exclusions** even when the primary question is about coverage.
4. **Never invent or extrapolate** — only state what is documented in the knowledge base below. If something is not documented, say so explicitly.
5. **Be precise about conditions** — waiting periods, occupancy rules, notification deadlines, etc.
6. **When multiple documents are loaded**, clarify which document your answer refers to.
7. **For ambiguous situations**, acknowledge the ambiguity and recommend consulting the relevant authority directly.
8. Use **structured formatting** — bold, bullet points, and clear headers for scannability.

---

## KNOWLEDGE BASE — LOADED DOCUMENTS

{knowledge_base}
"""


# ─── Assistant ────────────────────────────────────────────────────────────────

class InsuranceAssistant:
    """Singlife AI Assistant powered by Claude."""

    def __init__(self):
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        self.model = 'claude-sonnet-4-6'
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
        """Reload all documents from knowledge_base/ directory."""
        self.knowledge_base, self.documents = load_knowledge_base()
        self.system_prompt = build_system_prompt(self.knowledge_base)
        logger.info("Knowledge base reloaded")

    def is_available(self) -> bool:
        return self.client is not None

    def chat_stream(self, messages: list) -> Iterator[str]:
        """
        Stream a response from Claude given conversation history.
        messages: list of {"role": "user"|"assistant", "content": "..."}
        """
        if not self.client:
            yield (
                "**Configuration Error:** `ANTHROPIC_API_KEY` is not set or invalid. "
                "Add a valid key to `backend/.env` and restart the server.\n\n"
                "Get your key at: https://console.anthropic.com/"
            )
            return

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=2048,
                system=self.system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            yield f"\n\n**Error communicating with Claude API:** {str(e)}"
