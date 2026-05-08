# Local Setup and Run Flow

## Executive Summary
The project runs locally as a Flask backend serving a static frontend. Setup is lightweight but depends on valid LLM credentials and local Python environment consistency.

## Local Prerequisites
- Python environment compatible with listed dependencies
- Internet access for Anthropic API calls
- Optional: local CPU capacity for embedding model initialization (`all-MiniLM-L6-v2`)

## Setup Steps (Local Only)
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Create env file:
   - Copy `.env.example` to `backend/.env` (or create `backend/.env` manually)
3. Set minimum required env:
   - `ANTHROPIC_API_KEY`
4. Start app:
   - `python backend/app.py`
5. Open browser:
   - `http://localhost:5003` (or configured `PORT`)

## Default Local Runtime Behavior
- Server binds to `127.0.0.1` by default unless `FLASK_HOST` overridden.
- CORS is same-origin by default unless `ALLOWED_ORIGINS` configured.
- KB indexing runs at startup and after KB changes.

## Local Data Lifecycle
- Upload KB docs via `/api/upload` or place supported files into `knowledge_base/`.
- Chroma index and manifest are maintained in `chroma_db/`.
- QA and audit logs are appended to `logs/`.
- Conversation state persists in browser `localStorage`.

## Developer Verification Checklist
- `/api/status` shows AI availability and model.
- Document list updates after upload/delete.
- `evaluate` mode returns deterministic outputs with streamed explanation.
- `chat` mode answers grounded in KB context.
- Logs are being written to `logs/`.

## Known Local Ops Considerations
- Missing `ADMIN_API_KEY` or `AUDIT_API_KEY` enables dev-mode access to protected endpoints.
- If `ANTHROPIC_API_KEY` is invalid, app runs but AI features return configuration errors.
- Re-indexing performance depends on KB size and embedding runtime.
