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

load_dotenv(dotenv_path=Path(__file__).parent / '.env', override=True)

from services.claude_service import InsuranceAssistant, KB_DIR
from services.audit_log import log_audit, get_audit_logs
from services.rag_service import extract_text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)
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
    return send_from_directory(app.static_folder, 'audit.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    """stream claude's response back via SSE so we get the typing effect"""
    data = request.get_json(silent=True)
    if not data or 'messages' not in data:
        return jsonify({'error': 'Request body must include a "messages" array'}), 400

    messages = data['messages']
    if not isinstance(messages, list) or len(messages) == 0:
        return jsonify({'error': 'messages must be a non-empty array'}), 400

    mode = data.get('mode', 'chat')
    user_msg = messages[-1].get('content', '')[:200] if messages else ''
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
    return jsonify({
        'status': 'online',
        'platform': 'Singlife',
        'feature': 'AI Operations Assistant — SOP Decisioning & Document Intelligence',
        'ai_available': assistant.is_available(),
        'model': assistant.model if assistant.is_available() else None,
        'documents': assistant.documents,
    })


@app.route('/api/documents', methods=['GET'])
def list_documents():
    return jsonify({'documents': assistant.documents})


@app.route('/api/upload', methods=['POST'])
def upload_document():
    """Upload a document into knowledge_base/.
    Supported types: .txt, .pdf, .xlsx.
    Raw files are saved directly — the incremental indexer handles extraction."""
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
    out_path = KB_DIR / f"{slug}{ext}"

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
    """Use Case 2: generate empathetic customer email for UW decisions"""
    data = request.get_json(silent=True)
    if not data or 'emailData' not in data:
        return jsonify({'error': 'Request body must include "emailData"'}), 400

    email_data = data['emailData']
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
    """Use Case 3: QA review of underwriting results"""
    data = request.get_json(silent=True)
    if not data or 'qaData' not in data:
        return jsonify({'error': 'Request body must include "qaData"'}), 400

    qa_data = data['qaData']
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
                reasoning_summary='; '.join(
                    f"{b[0]}: {b[2]}" for b in qa_score.get('breakdown', []) if b[1] > 0
                ) or 'No risk factors',
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
    """pull recent Q&A logs — we use this to find patterns and knowledge gaps"""
    limit = request.args.get('limit', 50, type=int)
    logs = assistant.get_qa_logs(limit=limit)
    return jsonify({'logs': logs, 'total': len(logs)})


@app.route('/api/audit-logs', methods=['GET'])
def get_audit_logs_endpoint():
    """pull audit trail entries for compliance review"""
    limit = request.args.get('limit', 100, type=int)
    mode_filter = request.args.get('mode', None)
    logs = get_audit_logs(limit=limit, mode_filter=mode_filter)
    return jsonify({'audit_logs': logs, 'total': len(logs)})


@app.route('/api/documents/<filename>', methods=['DELETE'])
def delete_document(filename):
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
    logger.info(f"Starting Singlife AI Assistant on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
