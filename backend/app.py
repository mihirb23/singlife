# app.py — main flask server for our AI ops prototype
# routes for chat, case evaluation, doc uploads etc.
# NTU x Singlife veNTUre Sprint 2

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import json
import logging
import re
import tempfile
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / '.env', override=False)

from services.claude_service import InsuranceAssistant, KB_DIR
from services.audit_log import log_audit, get_audit_logs, check_audit_auth
from services.rag_service import extract_text
from services.privacy_filter import PrivacyFilter

# admin auth — protects mutating + listing endpoints (upload / delete / list / qa-logs).
# enforcement is controlled by ADMIN_API_KEY env var:
#   - set:   require X-Admin-Key header on protected endpoints (recommended)
#   - empty: dev mode, allow all access (warn on first hit)
def _admin_key() -> str:
    return os.getenv('ADMIN_API_KEY', '')

_ADMIN_DEV_WARNED = {'logged': False}

def check_admin_auth(headers) -> bool:
    """Verify admin access. Same pattern as audit auth."""
    key = _admin_key()
    if not key:
        if not _ADMIN_DEV_WARNED['logged']:
            logger.warning("ADMIN_API_KEY not set — admin endpoints are publicly accessible (dev mode)")
            _ADMIN_DEV_WARNED['logged'] = True
        return True
    return headers.get('X-Admin-Key') == key

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class PIILogFilter(logging.Filter):
    """Strip PII from log records. Uses track=False so the PrivacyFilter's
    pii_map doesn't accumulate forever on a long-running process — logs are
    never restored, so we don't need the mapping."""
    def __init__(self):
        super().__init__()
        self._pf = PrivacyFilter()

    def filter(self, record):
        record.msg = self._pf.sanitize_text(str(record.msg), track=False)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._pf.sanitize_text(str(v), track=False) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._pf.sanitize_text(str(a), track=False) for a in record.args)
        return True


logging.root.addFilter(PIILogFilter())

app = Flask(__name__, static_folder='../frontend', static_url_path='')
# CORS: lock to specific origins via ALLOWED_ORIGINS env (comma-separated).
# Default to same-origin only — set 'ALLOWED_ORIGINS=*' explicitly for dev if needed.
_allowed_origins_env = os.getenv('ALLOWED_ORIGINS', '').strip()
if _allowed_origins_env == '*':
    CORS(app)
    logger.warning("CORS: ALLOWED_ORIGINS=* — any website can call this API")
elif _allowed_origins_env:
    CORS(app, origins=[o.strip() for o in _allowed_origins_env.split(',') if o.strip()])
else:
    # default: no CORS headers added — only same-origin frontend works
    pass
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50mb max upload

assistant = InsuranceAssistant()
CHAT_LOCAL_ALLOWED = {'.txt', '.pdf', '.xlsx'}
CHAT_LOCAL_MAX_FILES = 5
CHAT_LOCAL_MAX_FILE_BYTES = 5 * 1024 * 1024
CHAT_LOCAL_MAX_TEXT_CHARS = 200000


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/architecture.html')
def architecture():
    return send_from_directory(app.static_folder, 'architecture.html')


@app.route('/audit')
def audit_page():
    """Audit viewer page. W-6 fix: ship a CSP header so any rogue HTML in audit
    fields can't execute scripts in the browser if rendered by the viewer."""
    response = send_from_directory(app.static_folder, 'audit.html')
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.route('/api/chat', methods=['POST'])
def chat():
    """stream claude's response back via SSE so we get the typing effect"""
    data = request.get_json(silent=True)
    if not data or 'messages' not in data:
        log_audit(mode='chat', input_reference={'error': 'missing messages'},
                  status='error', error='Request body must include a "messages" array')
        return jsonify({'error': 'Request body must include a "messages" array'}), 400

    messages = data['messages']
    if not isinstance(messages, list) or len(messages) == 0:
        log_audit(mode='chat', input_reference={'error': 'empty messages array'},
                  status='error', error='messages must be a non-empty array')
        return jsonify({'error': 'messages must be a non-empty array'}), 400

    mode = data.get('mode', 'chat')
    # mask PII before audit-log capture — chat free text can contain NRIC/email/phone
    _pf = PrivacyFilter()
    user_msg = _pf.sanitize_text(messages[-1].get('content', ''))[:200] if messages else ''
    local_attachments = data.get('localAttachments', [])
    if not isinstance(local_attachments, list):
        local_attachments = []
    local_attachments = local_attachments[:CHAT_LOCAL_MAX_FILES]
    normalized_attachments = []
    for item in local_attachments:
        if not isinstance(item, dict):
            continue
        text = str(item.get('text', '')).strip()
        if not text:
            continue
        normalized_attachments.append({
            'id': str(item.get('id', '')),
            'filename': str(item.get('filename', 'attachment')),
            'filetype': str(item.get('filetype', 'txt')),
            'text': text[:CHAT_LOCAL_MAX_TEXT_CHARS],
        })

    def generate():
        full_response = ''
        error_msg = None
        try:
            for chunk in assistant.chat_stream(messages, mode=mode, local_attachments=normalized_attachments):
                full_response += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            error_msg = str(e)
            yield f"data: {json.dumps({'text': f'Error: {error_msg}'})}\n\n"
        finally:
            log_audit(
                mode='chat',
                input_reference={'question': user_msg},
                output_result={'response_length': len(full_response)},
                status='error' if error_msg else 'success',
                error=error_msg,
            )
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route('/api/status', methods=['GET'])
def status():
    available = assistant.is_available()  # call once
    return jsonify({
        'status': 'online',
        'platform': 'Singlife',
        'feature': 'AI Operations Assistant — SOP Decisioning & Document Intelligence',
        'ai_available': available,
        'model': assistant.model if available else None,
        'documents': assistant.documents,
    })


@app.route('/api/documents', methods=['GET'])
def list_documents():
    return jsonify({'documents': assistant.documents})


@app.route('/api/upload', methods=['POST'])
def upload_document():
    """Upload a document into knowledge_base/.
    Supported types: .txt, .pdf, .xlsx.
    Raw files are saved directly — the incremental indexer handles extraction.
    Requires X-Admin-Key header when ADMIN_API_KEY is set (uploads change RAG context)."""
    if not check_admin_auth(request.headers):
        return jsonify({'error': 'Unauthorized — provide valid X-Admin-Key header'}), 401
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    filename = file.filename
    ext = Path(filename).suffix.lower()
    allowed = {'.txt', '.pdf', '.xlsx'}

    if ext not in allowed:
        return jsonify({'error': f'Unsupported file type. Upload a {", ".join(allowed)} file.'}), 400

    KB_DIR.mkdir(exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '_', Path(filename).stem.lower()).strip('_')
    if not slug:
        slug = 'document'
    out_path = KB_DIR / f"{slug}{ext}"

    # don't silently overwrite — if a file with this slug already exists, append a
    # numeric suffix so two files with similar names (my-file.pdf vs my_file.pdf)
    # don't trample each other
    overwritten = False
    if out_path.exists():
        # if it's the literal same source filename, allow overwrite (re-upload of same doc)
        if out_path.name == f"{slug}{ext}" and Path(filename).name.lower() == out_path.name.lower():
            overwritten = True
        else:
            counter = 2
            while (KB_DIR / f"{slug}_{counter}{ext}").exists():
                counter += 1
            out_path = KB_DIR / f"{slug}_{counter}{ext}"

    if ext == '.txt':
        text = file.read().decode('utf-8', errors='replace')
        header = (
            f"# {Path(filename).stem}\n"
            f"Source file: {filename}\n\n"
            f"{'─' * 80}\n\n"
        )
        out_path.write_text(header + text, encoding='utf-8')
        size_display = f"{len(text):,} chars"
    else:
        raw = file.read()
        out_path.write_bytes(raw)
        size_display = f"{len(raw):,} bytes"

    logger.info(f"Document uploaded: {filename} → {out_path.name} ({size_display})")

    assistant.reload_knowledge_base()

    return jsonify({
        'success': True,
        'filename': out_path.name,
        'overwritten': overwritten,  # surface so UI can show "replaced existing file" if true
        'chars': out_path.stat().st_size,
        'documents': assistant.documents,
    })


@app.route('/api/chat/upload-local', methods=['POST'])
def upload_chat_local():
    """Upload a file for chat-local context only.
    This does NOT write to knowledge_base/ and does NOT trigger re-index."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    filename = file.filename
    ext = Path(filename).suffix.lower()
    if ext not in CHAT_LOCAL_ALLOWED:
        return jsonify({'error': f'Unsupported file type. Upload a {", ".join(sorted(CHAT_LOCAL_ALLOWED))} file.'}), 400

    raw = file.read()
    if len(raw) > CHAT_LOCAL_MAX_FILE_BYTES:
        return jsonify({'error': 'File too large. Max size is 5 MB for chat-local uploads.'}), 400

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)

        text = extract_text(tmp_path)
        if not text or not text.strip():
            return jsonify({'error': 'Could not extract readable text from this file.'}), 400

        trimmed = text.strip()
        if len(trimmed) > CHAT_LOCAL_MAX_TEXT_CHARS:
            trimmed = trimmed[:CHAT_LOCAL_MAX_TEXT_CHARS]

        return jsonify({
            'success': True,
            'attachment': {
                'id': uuid.uuid4().hex,
                'filename': filename,
                'filetype': ext.lstrip('.'),
                'text': trimmed,
                'chars': len(trimmed),
            }
        })
    except Exception as e:
        logger.error(f"Chat-local upload extraction failed for {filename}: {e}")
        return jsonify({'error': f'Failed to process file: {str(e)}'}), 400
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@app.route('/api/evaluate', methods=['POST'])
def evaluate_case():
    """hybrid evaluation — rules engine runs first, then claude explains the results"""
    data = request.get_json(silent=True)
    if not data or 'caseData' not in data:
        # W-4 fix: log validation failures so SRE can answer "how many bad requests today"
        log_audit(mode='evaluate',
                  input_reference={'error': 'missing caseData'},
                  status='error',
                  error='Request body must include "caseData"')
        return jsonify({'error': 'Request body must include "caseData"'}), 400

    case_data = data['caseData']
    messages = data.get('messages', [])

    # run rules engine separately so we can capture result for audit log
    rules_result = assistant.evaluate_with_rules_engine(case_data)
    case_id = None
    input_ref = {}
    output_ref = {}
    reasoning = None

    if rules_result and 'error' not in rules_result:
        case_id = rules_result.get('contract_no')
        input_ref = {
            'channel': rules_result.get('channel'),
            'contract_no': rules_result.get('contract_no'),
            'plan_code': rules_result.get('cnt_type'),
        }
        output_ref = {
            'decision': rules_result.get('overall_decision'),
            'trigger': rules_result.get('automation_trigger'),
            'steps_failed': rules_result.get('steps_failed', []),
            'outstanding_followups': rules_result.get('outstanding_followups', ''),
        }
        reasoning = rules_result.get('decision_reason')

    def generate():
        full_response = ''
        error_msg = None
        try:
            for chunk in assistant.evaluate_stream(case_data, messages):
                full_response += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            error_msg = str(e)
            yield f"data: {json.dumps({'text': f'Error: {error_msg}'})}\n\n"
        finally:
            log_audit(
                mode='evaluate',
                case_id=case_id,
                input_reference=input_ref,
                output_result=output_ref,
                reasoning_summary=reasoning,
                status='error' if error_msg else 'success',
                error=error_msg,
            )
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route('/api/generate-email', methods=['POST'])
def generate_email():
    """Use Case 2: generate empathetic customer email for UW decisions.
    Accepts payload under 'emailData' (preferred) or 'caseData' (alias)."""
    data = request.get_json(silent=True)
    if not data:
        log_audit(mode='email', input_reference={'error': 'no body'},
                  status='error', error='Request body required')
        return jsonify({'error': 'Request body required'}), 400
    email_data = data.get('emailData') or data.get('caseData')
    if not email_data:
        log_audit(mode='email', input_reference={'error': 'missing emailData/caseData'},
                  status='error', error='Missing payload key')
        return jsonify({'error': 'Request body must include "emailData" (or "caseData" alias)'}), 400

    messages = data.get('messages', [])

    decision_type = email_data.get('decision_type', 'unknown')
    tone = email_data.get('tone_required', 'unknown')

    def generate():
        full_response = ''
        error_msg = None
        try:
            for chunk in assistant.email_draft_stream(email_data, messages):
                full_response += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            error_msg = str(e)
            yield f"data: {json.dumps({'text': f'Error: {error_msg}'})}\n\n"
        finally:
            log_audit(
                mode='email',
                input_reference={'decision_type': decision_type, 'tone': tone},
                output_result={'email_length': len(full_response)},
                reasoning_summary=f'{decision_type} email drafted',
                status='error' if error_msg else 'success',
                error=error_msg,
            )
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route('/api/qa-review', methods=['POST'])
def qa_review():
    """Use Case 3: QA review of underwriting results.
    Accepts payload under 'qaData' (preferred) or 'caseData' (alias)."""
    data = request.get_json(silent=True)
    if not data:
        log_audit(mode='qa_review', input_reference={'error': 'no body'},
                  status='error', error='Request body required')
        return jsonify({'error': 'Request body required'}), 400
    qa_data = data.get('qaData') or data.get('caseData')
    if not qa_data:
        log_audit(mode='qa_review', input_reference={'error': 'missing qaData/caseData'},
                  status='error', error='Missing payload key')
        return jsonify({'error': 'Request body must include "qaData" (or "caseData" alias)'}), 400

    messages = data.get('messages', [])

    qa_case_id = qa_data.get('case_id', qa_data.get('case_metadata', {}).get('case_id'))
    qa_decision = qa_data.get('decision', qa_data.get('case_metadata', {}).get('decision'))
    icd_cnt = qa_data.get('icd_cnt', qa_data.get('qa_indicators', {}).get('icd_cnt', 0))

    # pre-calculate score for audit log
    qa_score = assistant._calculate_qa_score(qa_data)

    def generate():
        full_response = ''
        error_msg = None
        try:
            for chunk in assistant.qa_review_stream(qa_data, messages):
                full_response += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            error_msg = str(e)
            yield f"data: {json.dumps({'text': f'Error: {error_msg}'})}\n\n"
        finally:
            log_audit(
                mode='qa_review',
                case_id=qa_case_id,
                input_reference={'decision': qa_decision, 'icd_count': icd_cnt},
                output_result={
                    'risk_level': qa_score.get('risk_level'),
                    'complexity_score': qa_score.get('complexity_score'),
                    'recommendation': qa_score.get('recommendation'),
                },
                # W-8 fix: prefix each item with "Risk factor:" so operators don't misread
                # an internal scoring label (e.g. "New Underwriter: 0 years (<2)") as a
                # description of the case
                reasoning_summary='; '.join(
                    f"Risk factor — {b[0]}: {b[2]}" for b in qa_score.get('breakdown', []) if b[1] > 0
                ) or 'No risk factors flagged',
                status='error' if error_msg else 'success',
                error=error_msg,
            )
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Pull recent Q&A logs — we use this to find patterns and knowledge gaps.
    Requires X-Admin-Key header when ADMIN_API_KEY is set (logs may contain query content).
    The qa_log reader caps limit at MAX_QA_LOG_LIMIT to protect memory."""
    if not check_admin_auth(request.headers):
        return jsonify({'error': 'Unauthorized — provide valid X-Admin-Key header'}), 401
    limit = request.args.get('limit', 50, type=int)
    logs = assistant.get_qa_logs(limit=limit)
    return jsonify({'logs': logs, 'total': len(logs)})


@app.route('/api/audit-logs', methods=['GET'])
def get_audit_logs_endpoint():
    """Pull audit trail entries for compliance review.
    Requires X-Audit-Key header when AUDIT_API_KEY is set.

    Query params (W-3 fix):
      limit  — max entries (default 100, max 10000)
      offset — skip first N matching entries (default 0)
      mode   — filter by mode: chat / evaluate / email / qa_review
      from   — ISO 8601 lower bound (e.g. 2026-01-01T00:00:00Z)
      to     — ISO 8601 upper bound
    """
    if not check_audit_auth(request.headers):
        return jsonify({'error': 'Unauthorized — provide valid X-Audit-Key header'}), 401

    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    mode_filter = request.args.get('mode', None)
    date_from = request.args.get('from', None)
    date_to = request.args.get('to', None)

    result = get_audit_logs(
        limit=limit,
        mode_filter=mode_filter,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
    )
    # malformed date filter — bubble up as 400 instead of silently returning 0
    if 'error' in result:
        return jsonify({'error': result['error']}), 400
    return jsonify({
        'audit_logs': result['entries'],
        'total': len(result['entries']),
        'total_matched': result['total_matched'],
        'limit': result['limit'],
        'offset': result['offset'],
        'has_more': result['has_more'],
        'skipped_corrupt_lines': result['skipped'],
    })


@app.route('/api/documents/<filename>', methods=['DELETE'])
def delete_document(filename):
    """Delete a KB file. Requires X-Admin-Key header when ADMIN_API_KEY is set."""
    if not check_admin_auth(request.headers):
        return jsonify({'error': 'Unauthorized — provide valid X-Admin-Key header'}), 401
    # basic path traversal check — don't want anyone deleting files outside kb
    file_path = (KB_DIR / filename).resolve()
    if not str(file_path).startswith(str(KB_DIR.resolve())):
        return jsonify({'error': 'Invalid filename'}), 400
    if not file_path.exists():
        return jsonify({'error': 'Document not found'}), 404

    file_path.unlink()
    logger.info(f"Document deleted: {filename}")
    assistant.reload_knowledge_base()

    return jsonify({
        'success': True,
        'documents': assistant.documents,
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5003))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    # default to localhost — set FLASK_HOST=0.0.0.0 explicitly to bind all interfaces.
    # this stops accidental network exposure on dev laptops on shared wifi.
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    logger.info(f"Starting Singlife AI Assistant on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
