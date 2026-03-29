# Singlife AI Ops Assistant

AI-powered operations assistant built for Singlife's New Business Insurance Group (NBIG). This tool helps ops staff process insurance applications faster by evaluating cases against SOPs, answering questions about policies, and flagging knowledge gaps — all grounded in uploaded documents.

Built as part of the **Singlife x NTU veNTUre** project (Mar–May 2026).

---

## What it does

### 1. SOP Case Evaluation
Paste case data (from L400 / UAT extractions) and the AI evaluates it step-by-step against the NBIG pre-issue checklist (SOP-NBIG-STP-001). It checks:
- Document submissions (MyInfo, benefit illustration, application form)
- Client number search and duplicate detection
- Client info validation (sex, address, DOB, NRIC, nationality vs L400)
- Contract info (premium amounts, payment modes)
- Follow-up code status (CSL, F45, C09, etc.)
- Jet underwriting indicators (ANB/SA thresholds, UW sub-std, decline, postpone, claim ind)

Then outputs a structured decision: **Standard** / **Standard with Further Requirements** / **Refer to UW** / **Trigger GNS Review** / **Trigger Compliance** / **Withdrawal** — with a JSON automation trigger payload.

### 2. General Q&A (Chat Mode)
Ask questions about SOPs, policy documents, or operational processes. Answers are grounded only in uploaded documents — the AI never guesses or uses external knowledge. Cites specific SOP steps and sections.

### 3. Knowledge Gap Detection
When the AI can't answer confidently, it flags exactly what's missing from the SOP, which step the gap is in, and what clarification is needed from SMEs. This feeds into the learning loop.

### 4. Q&A Logging
Every question and response is logged to `logs/qa_log.jsonl` with timestamps and mode info. This data supports the feedback/learning loop — helps identify recurring questions, SOP gaps, and areas for improvement.

---

## Architecture

```
frontend/ (vanilla JS + CSS)
    |
    |-- Chat mode -----> POST /api/chat --------\
    |-- Evaluate mode -> POST /api/evaluate -----+---> Claude API (streaming SSE)
    |                                            |
backend/ (Flask)                                 |
    |-- services/claude_service.py               |
    |       loads knowledge_base/*.txt           |
    |       builds system prompt                 |
    |       streams response + logs Q&A          |
    |                                            |
knowledge_base/                                  |
    |-- sop_nbig_stp_001.txt  (SOP rules)  <----/
    |-- homesecure_income_sg.txt (policy doc)
    |-- (any uploaded PDFs/TXTs)
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Flask (Python) |
| AI | Claude API (Anthropic SDK) — streaming via SSE |
| Frontend | Vanilla JS, HTML, CSS (dark theme) |
| Markdown | marked.js |
| PDF extraction | pypdf |
| Storage | Local filesystem (knowledge_base/ for docs, logs/ for Q&A) |
| Conversations | Browser localStorage |

---

## Project Structure

```
singlife/
├── backend/
│   ├── app.py                      # flask routes (chat, evaluate, upload, logs, etc.)
│   ├── services/
│   │   ├── __init__.py
│   │   └── claude_service.py       # claude integration, system prompt, Q&A logging
│   └── .env                        # your api key goes here (not tracked)
├── frontend/
│   ├── index.html                  # main page with mode toggle
│   ├── js/app.js                   # UI logic, streaming, conversation management
│   └── css/styles.css              # dark minimal theme
├── knowledge_base/
│   ├── sop_nbig_stp_001.txt        # NBIG pre-issue checks SOP (the main rules)
│   └── homesecure_income_sg.txt    # sample policy document
├── scripts/
│   └── add_policy.py               # CLI tool to extract PDF -> knowledge_base/
├── logs/                           # Q&A logs (auto-created, gitignored)
├── .env.example                    # config template
├── requirements.txt                # python dependencies
└── README.md
```

---

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Serves the frontend |
| GET | `/api/status` | AI availability, model info, loaded documents |
| GET | `/api/documents` | List all knowledge base documents |
| POST | `/api/upload` | Upload a PDF/TXT to the knowledge base |
| DELETE | `/api/documents/<filename>` | Remove a document |
| POST | `/api/chat` | Stream a Q&A response (SSE) |
| POST | `/api/evaluate` | Evaluate case data against SOP rules (SSE) |
| GET | `/api/logs` | Get recent Q&A logs for learning loop |

---

## Setup

### 1. Clone

```bash
git clone https://github.com/mihirb23/mysinglife.git
cd mysinglife
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add your API key

```bash
cp .env.example backend/.env
# edit backend/.env and add your Anthropic API key
```

### 4. Run

```bash
PORT=5003 python backend/app.py
```

Open http://localhost:5003

---

## How to Use

### Chat Mode
1. Open the app, make sure sidebar shows documents loaded (green dot = AI online)
2. Type a question like: *"What checks are required for QnB CareShield cases?"*
3. AI answers grounded in the SOP with step references

### Evaluate Mode
1. Click **Evaluate Case** in the sidebar toggle
2. Paste case data as JSON, e.g.:

```json
{
  "contractNo": "G0406789",
  "cntType": "EYA",
  "channel": "QnB",
  "clientNo": "55167349",
  "nric": "S8483123I",
  "surname": "Long",
  "givenName": "Quan Zhi",
  "sex": "M",
  "dob": "1988-08-08",
  "nationality": "SG",
  "l400_nric": "S8483123I",
  "l400_name": "Client Fields Test",
  "l400_sex": "M",
  "l400_dob": "1988-08-08",
  "l400_nationality": "SG",
  "followUpCodes": [{"code": "CSL", "status": "O"}],
  "anb": 38,
  "totalAggregateSA": 8000,
  "uwSubStd": "N",
  "decline": "N",
  "postpone": "N",
  "claimInd": "N"
}
```

3. AI runs through every SOP step and outputs:
   - Rule-by-rule evaluation (pass/fail/manual review)
   - Overall decision
   - Ops outcome (what to do next)
   - Automation trigger JSON

### Upload Documents
Click **Upload document** in the sidebar to add more SOPs or policy PDFs. The knowledge base reloads automatically.

---

## Configuration

All config is via environment variables in `backend/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Which Claude model to use |
| `CLAUDE_MAX_TOKENS` | `4096` | Max response tokens |
| `PORT` | `5003` | Server port |
| `FLASK_DEBUG` | `false` | Debug mode |

---

## Key SOP: SOP-NBIG-STP-001

This is the core document the AI uses for case evaluation. It covers the full NBIG new business pre-issue workflow:

| Category | Steps | What it checks |
|----------|-------|---------------|
| Open Documents | 1A–1C | Identity doc, benefit illustration, application form |
| Document Checks | 2A | MyInfo consent timestamp (1-year validity) |
| Client Number Search | 3A | NRIC lookup on L400 |
| Duplicate Client Checks | 4A–4C | Name/DOB/sex matching, client patching |
| Client Info Checks | 5A–5D | Sex, address, mobile, email, nationality, NRIC, DOB |
| Contract Info Checks | 6A–6I | Premium, birthday crossover, ERI, payment mode |
| Follow-Up Code Checks | 7A–7C | All follow-ups resolved (R)? |
| Jet Underwriting | 8A–8H | ANB/SA limits, UW indicators, RCS checks |
| Decision | 9A | Lock case with appropriate decision path |

Decision outcomes: Standard, Standard with Requirements, Refer to UW, Trigger GNS, Trigger Compliance, Withdrawal.

---

## Sprint 2 Context

This project was built for Sprint 2 of the Singlife x NTU veNTUre project. The sprint goal was to validate the end-to-end AI Ops concept:

**Knowledge (structured SOPs) -> AI Reasoning (traceable decisions) -> Automation (trigger outputs)**

This is a prototype — no real data, no production systems, no live deployments. All case data is from UAT environments.

---

## Team

- **Project Partner:** Singlife
- **Project Sponsor:** May Yang
- **Process Automation SMEs:** Terence Loo, Sharon Yong
- **Technical Advisor:** David Sun
