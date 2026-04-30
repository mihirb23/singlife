# audit_log.py — compliance audit trail for all AI operations
# every API request gets one JSONL entry in logs/audit_log.jsonl
# fields per David's requirements (2026-04-17):
#   request_id, timestamp, input_reference, decision/output,
#   rule/SOP/KB versions, reasoning_summary, status/error

import json
import uuid
import os
import logging
import fcntl
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).parent.parent.parent / 'logs'
AUDIT_FILE = LOG_DIR / 'audit_log.jsonl'
KB_DIR = Path(__file__).parent.parent.parent / 'knowledge_base'

# ensure log dir exists once at import — saves an mkdir on every audit write
LOG_DIR.mkdir(exist_ok=True)


def _get_audit_api_key() -> str:
    """Read the key live so .env reloads / runtime changes take effect.
    Reading os.getenv on each call is cheap (it's a dict lookup)."""
    return os.getenv('AUDIT_API_KEY', '')


# version cache — invalidate on file mtime change so SME edits take effect without restart
_VERSIONS_CACHE: dict = {}
_VERSIONS_MTIMES: dict = {}


def _get_versions() -> dict:
    """Read current versions from config files + env. Cached by file mtime
    so we don't read sop_rules.json + qa_scoring_rules.json on every audit write."""
    sop_path = KB_DIR / 'sop_rules.json'
    qa_path = KB_DIR / 'qa_scoring_rules.json'

    sop_mtime = sop_path.stat().st_mtime if sop_path.exists() else 0
    qa_mtime = qa_path.stat().st_mtime if qa_path.exists() else 0
    model = os.getenv('CLAUDE_MODEL', 'unknown')

    # cache key includes both mtimes + model so any change invalidates
    cache_key = (sop_mtime, qa_mtime, model)
    if _VERSIONS_CACHE and _VERSIONS_MTIMES.get('key') == cache_key:
        return dict(_VERSIONS_CACHE)  # return a copy so callers can't mutate cache

    versions = {
        'model': model,
        'sop_rules': 'unknown',
        'qa_scoring': 'unknown',
    }
    try:
        if sop_path.exists():
            rules = json.loads(sop_path.read_text(encoding='utf-8'))
            versions['sop_rules'] = rules.get('version', 'unknown')
            versions['sop_id'] = rules.get('sop_id', 'unknown')
    except Exception:
        pass
    try:
        if qa_path.exists():
            qa = json.loads(qa_path.read_text(encoding='utf-8'))
            versions['qa_scoring'] = qa.get('version', 'unknown')
    except Exception:
        pass

    _VERSIONS_CACHE.clear()
    _VERSIONS_CACHE.update(versions)
    _VERSIONS_MTIMES['key'] = cache_key
    return dict(versions)


def check_audit_auth(request_headers) -> bool:
    """Verify audit API access. Returns True if authorized.
    Reads key live so .env updates after import take effect."""
    key = _get_audit_api_key()
    if not key:
        # no key configured — allow access (dev mode), but warn loudly
        if not _AUTH_WARNING_LOGGED.get('audit'):
            logger.warning("AUDIT_API_KEY not set — /api/audit-logs is publicly accessible (dev mode)")
            _AUTH_WARNING_LOGGED['audit'] = True
        return True
    return request_headers.get('X-Audit-Key') == key


_AUTH_WARNING_LOGGED: dict = {}


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
    request_id = str(uuid.uuid4())
    entry = {
        'request_id': request_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'mode': mode,
        'case_id': case_id,
        'input_reference': input_reference or {},
        'output_result': output_result or {},
        'versions': _get_versions(),
        'reasoning_summary': reasoning_summary,
        'status': status,
        'error': error,
    }

    # W-5 fix: use fcntl.LOCK_EX so concurrent gunicorn workers don't interleave writes.
    # JSONL append is usually atomic for lines <= PIPE_BUF (4KB) on POSIX, but a 4-worker
    # deployment can occasionally produce corrupt lines without an explicit lock.
    try:
        with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(json.dumps(entry, default=str) + '\n')
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"Audit log write failed: {e}")

    return request_id


def _validate_iso_date(s: str) -> bool:
    """Loose ISO 8601 date check — accepts 2026-01-01 or 2026-01-01T12:34:56(Z)?.
    Returns True if parseable, False otherwise. Used to reject malformed
    date filters with a clear error instead of silently matching nothing."""
    if not s:
        return True
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            continue
    return False


def get_audit_logs(
    limit: int = 100,
    mode_filter: str = None,
    offset: int = 0,
    date_from: str = None,
    date_to: str = None,
) -> dict:
    """Read audit entries with pagination + date-range filtering (W-3 fix).

    Args:
        limit: max entries to return (default 100, hard cap 10000 to protect memory)
        mode_filter: filter by mode (chat/evaluate/email/qa_review)
        offset: skip the first N matching entries (for paged compliance queries)
        date_from: ISO 8601 timestamp — include entries >= this time (inclusive)
        date_to: ISO 8601 timestamp — include entries <= this time (inclusive)

    Returns dict with entries, skipped count, total_matched (pre-pagination), and pagination info.
    Sets 'error' key if a date filter is malformed.
    """
    # cap limit to protect memory on huge logs
    limit = max(1, min(limit, 10000))
    offset = max(0, offset)

    # validate date filters early so a malformed input doesn't silently match nothing
    if not _validate_iso_date(date_from):
        return {'entries': [], 'skipped': 0, 'total_matched': 0,
                'limit': limit, 'offset': offset, 'has_more': False,
                'error': f"Invalid 'from' date format: '{date_from}' — expected ISO 8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)"}
    if not _validate_iso_date(date_to):
        return {'entries': [], 'skipped': 0, 'total_matched': 0,
                'limit': limit, 'offset': offset, 'has_more': False,
                'error': f"Invalid 'to' date format: '{date_to}' — expected ISO 8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)"}
    # reject reversed range so "from=2026-12-01&to=2026-01-01" doesn't silently return 0
    if date_from and date_to and date_from > date_to:
        return {'entries': [], 'skipped': 0, 'total_matched': 0,
                'limit': limit, 'offset': offset, 'has_more': False,
                'error': f"'from' ({date_from}) is later than 'to' ({date_to}) — date range is empty"}

    if not AUDIT_FILE.exists():
        return {'entries': [], 'skipped': 0, 'total_matched': 0,
                'limit': limit, 'offset': offset, 'has_more': False}

    matched = []
    skipped = 0
    try:
        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as e:
                    skipped += 1
                    logger.warning(f"Skipping corrupt audit line {line_num}: {e}")
                    continue

                # mode filter
                if mode_filter and entry.get('mode') != mode_filter:
                    continue
                # date range filter — string comparison works for ISO 8601 timestamps
                ts = entry.get('timestamp', '')
                if date_from and ts < date_from:
                    continue
                if date_to and ts > date_to:
                    continue

                matched.append(entry)
    except Exception as e:
        logger.error(f"Audit log read failed: {e}")

    total = len(matched)
    # apply offset+limit at the end (most-recent-first by slicing tail)
    # reverse so newest is first, then offset+limit, then return
    page = list(reversed(matched))[offset:offset + limit]
    has_more = (offset + limit) < total

    return {
        'entries': page,
        'skipped': skipped,
        'total_matched': total,
        'limit': limit,
        'offset': offset,
        'has_more': has_more,
    }
