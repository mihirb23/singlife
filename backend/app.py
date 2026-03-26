"""
Singlife Platform — AI Assistant Backend
Flask server for the Document Intelligence Engine
"""

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import json
import logging
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / '.env', override=True)

from services.claude_service import InsuranceAssistant, KB_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload

assistant = InsuranceAssistant()


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json(silent=True)
    if not data or 'messages' not in data:
        return jsonify({'error': 'Request body must include a "messages" array'}), 400

    messages = data['messages']
    if not isinstance(messages, list) or len(messages) == 0:
        return jsonify({'error': 'messages must be a non-empty array'}), 400

    def generate():
        for chunk in assistant.chat_stream(messages):
            yield f"data: {json.dumps({'text': chunk})}\n\n"
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
        'feature': 'AI Assistant — Document Intelligence Engine',
        'ai_available': assistant.is_available(),
        'model': assistant.model if assistant.is_available() else None,
        'documents': assistant.documents,
    })


@app.route('/api/documents', methods=['GET'])
def list_documents():
    return jsonify({'documents': assistant.documents})


@app.route('/api/upload', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    filename = file.filename
    ext = Path(filename).suffix.lower()

    if ext == '.pdf':
        try:
            import pypdf
            reader = pypdf.PdfReader(file.stream)
            pages = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text.strip())
            text = "\n\n".join(pages)

            if not text.strip():
                return jsonify({'error': 'No text could be extracted. The PDF may be image-based (scanned).'}), 400
        except ImportError:
            return jsonify({'error': 'pypdf is not installed on the server'}), 500
        except Exception as e:
            return jsonify({'error': f'Failed to read PDF: {str(e)}'}), 400

    elif ext == '.txt':
        text = file.read().decode('utf-8', errors='replace')
    else:
        return jsonify({'error': 'Unsupported file type. Upload a .pdf or .txt file.'}), 400

    # Save to knowledge_base/
    KB_DIR.mkdir(exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '_', Path(filename).stem.lower()).strip('_')
    out_path = KB_DIR / f"{slug}.txt"

    header = (
        f"# {Path(filename).stem}\n"
        f"Source file: {filename}\n\n"
        f"{'─' * 80}\n\n"
    )
    out_path.write_text(header + text, encoding='utf-8')
    logger.info(f"Document uploaded: {filename} → {out_path.name} ({len(text):,} chars)")

    # Reload knowledge base
    assistant.reload_knowledge_base()

    return jsonify({
        'success': True,
        'filename': out_path.name,
        'chars': len(text),
        'documents': assistant.documents,
    })


@app.route('/api/documents/<filename>', methods=['DELETE'])
def delete_document(filename):
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
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    logger.info(f"Starting Singlife AI Assistant on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
