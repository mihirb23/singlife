# audit_log.py — compliance audit trail for all AI operations
# every API request gets one JSONL entry in logs/audit_log.jsonl
# fields per David's requirements (2026-04-17):
#   request_id, timestamp, input_reference, decision/output,
#   rule/SOP/KB versions, reasoning_summary, status/error

import json
import uuid
import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).parent.parent.parent / 'logs'
AUDIT_FILE = LOG_DIR / 'audit_log.jsonl'
KB_DIR = Path(__file__).parent.parent.parent / 'knowledge_base'


def _get_versions() -> dict:
    """Read current versions from config files + env."""
    versions = {
        'model': os.getenv('CLAUDE_MODEL', 'unknown'),
        'sop_rules': 'unknown',
        'qa_scoring': 'unknown',
    }
    try:
        rules = json.loads((KB_DIR / 'sop_rules.json').read_text(encoding='utf-8'))
        versions['sop_rules'] = rules.get('version', 'unknown')
        versions['sop_id'] = rules.get('sop_id', 'unknown')
    except Exception:
        pass
    try:
        qa = json.loads((KB_DIR / 'qa_scoring_rules.json').read_text(encoding='utf-8'))
        versions['qa_scoring'] = qa.get('version', 'unknown')
    except Exception:
        pass
    return versions


def log_audit(
    mode: str,
    case_id: str = None,
    input_reference: dict = None,
    output_result: dict = None,
    reasoning_summary: str = None,
    status: str = 'success',
    error: str = None,
) -> str:
    """Write one audit entry. Returns the request_id."""
    LOG_DIR.mkdir(exist_ok=True)

    request_id = str(uuid.uuid4())[:8]
    entry = {
        'request_id': request_id,
        'timestamp': datetime.now().isoformat(),
        'mode': mode,
        'case_id': case_id,
        'input_reference': input_reference or {},
        'output_result': output_result or {},
        'versions': _get_versions(),
        'reasoning_summary': reasoning_summary,
        'status': status,
        'error': error,
    }

    try:
        with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, default=str) + '\n')
    except Exception as e:
        logger.error(f"Audit log write failed: {e}")

    return request_id


def get_audit_logs(limit: int = 100, mode_filter: str = None) -> list:
    """Read last N audit entries, optionally filtered by mode."""
    if not AUDIT_FILE.exists():
        return []
    entries = []
    try:
        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if mode_filter and entry.get('mode') != mode_filter:
                    continue
                entries.append(entry)
    except Exception as e:
        logger.error(f"Audit log read failed: {e}")
    return entries[-limit:]
