# llm_debug_printer.py — TASK-AUDIT-001
# Terminal-print observer for LLM calls. Activated when LLM_PRINT_DEBUG=true
# so developers can see exactly what was sent to the Anthropic API in stdout.
# Disabled by default — must not affect production behavior.

import os
import sys
import json
import time
from datetime import datetime, timezone

SEP = '═' * 90
SUB = '─' * 90


def is_enabled() -> bool:
    """True only when LLM_PRINT_DEBUG=true (or 1 / yes). Off by default."""
    return os.getenv('LLM_PRINT_DEBUG', '').lower() in ('true', '1', 'yes')


def is_full_mode() -> bool:
    """True when LLM_PRINT_FULL=true — disables truncation so every field is
    visible for audit. Off by default; pair with LLM_PRINT_DEBUG=true."""
    return os.getenv('LLM_PRINT_FULL', '').lower() in ('true', '1', 'yes')


def print_request(mode: str, model: str, system: str, messages: list,
                  system_max_chars: int = 2000, msg_max_chars: int = 4000) -> float:
    """Print the LLM request to stdout. Returns the start timestamp so the caller
    can pass it to print_response() for duration calculation.

    LLM_PRINT_FULL=true disables truncation for audit runs — every field is
    printed regardless of size.
    """
    started_at = time.time()
    if not is_enabled():
        return started_at

    full_mode = is_full_mode()
    ts = datetime.now(timezone.utc).isoformat()
    sys_chars = len(system) if system else 0
    msg_count = len(messages) if messages else 0

    print(file=sys.stdout)
    print(SEP, file=sys.stdout)
    print(f"  [LLM CALL]  {ts}{'  [AUDIT FULL]' if full_mode else ''}", file=sys.stdout)
    print(f"  mode    : {mode}", file=sys.stdout)
    print(f"  model   : {model}", file=sys.stdout)
    print(f"  system  : {sys_chars} chars", file=sys.stdout)
    print(f"  messages: {msg_count}", file=sys.stdout)
    print(SEP, file=sys.stdout)

    # system prompt — full content if LLM_PRINT_FULL, otherwise truncated
    if full_mode:
        print(f"  ── system prompt ({sys_chars} chars, FULL) ──", file=sys.stdout)
        print(file=sys.stdout)
        print(system if system else "(empty)", file=sys.stdout)
    else:
        print(f"  ── system prompt (showing first {min(system_max_chars, sys_chars)} of {sys_chars} chars) ──",
              file=sys.stdout)
        print(file=sys.stdout)
        print(system[:system_max_chars] if system else "(empty)", file=sys.stdout)
        if sys_chars > system_max_chars:
            print(f"\n  ... [{sys_chars - system_max_chars} more chars truncated]", file=sys.stdout)
    print(file=sys.stdout)
    print(SUB, file=sys.stdout)

    # messages — full content if LLM_PRINT_FULL, otherwise truncated
    print(f"  ── messages ({msg_count}){' FULL' if full_mode else ''} ──", file=sys.stdout)
    print(file=sys.stdout)
    serialized = json.dumps(messages, default=str, indent=2, ensure_ascii=False) if messages else "[]"
    if full_mode or len(serialized) <= msg_max_chars:
        print(serialized, file=sys.stdout)
    else:
        print(serialized[:msg_max_chars], file=sys.stdout)
        print(f"\n  ... [{len(serialized) - msg_max_chars} more chars truncated]", file=sys.stdout)
    print(SEP, file=sys.stdout)
    sys.stdout.flush()
    return started_at


def print_response(mode: str, started_at: float, char_count: int = 0,
                   input_tokens: int = None, output_tokens: int = None,
                   error: str = None) -> None:
    """Print a short post-call summary: duration, output chars, tokens (if known)."""
    if not is_enabled():
        return
    elapsed = time.time() - started_at
    parts = [f"mode={mode}", f"duration={elapsed:.2f}s", f"output_chars={char_count}"]
    if input_tokens is not None:
        parts.append(f"input_tokens={input_tokens}")
    if output_tokens is not None:
        parts.append(f"output_tokens={output_tokens}")
    if error:
        parts.append(f"error={error}")
    status = "ERROR" if error else "DONE"
    print(f"  [LLM {status}]  {'  '.join(parts)}", file=sys.stdout)
    print(SEP, file=sys.stdout)
    print(file=sys.stdout)
    sys.stdout.flush()
