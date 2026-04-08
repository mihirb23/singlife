// app.js — handles all the frontend stuff: chat UI, streaming, mode switching, uploads
// pretty much a single-page app without any framework, just vanilla js
// NTU x Singlife veNTUre project

const API_BASE = '';

// app state — conversations persist in localStorage between sessions
let conversations = JSON.parse(localStorage.getItem('sl_convos') || '[]');
let activeId = null;
let isStreaming = false;
let currentMode = 'chat'; // 'chat' or 'evaluate'

// dom refs
const chatContainer  = document.getElementById('chatContainer');
const messagesEl     = document.getElementById('messages');
const welcomeEl      = document.getElementById('welcome');
const userInputEl    = document.getElementById('userInput');
const sendBtnEl      = document.getElementById('sendBtn');
const chatInputEl    = document.getElementById('chatInput');
const chatSendBtnEl  = document.getElementById('chatSendBtn');
const bottomInputEl  = document.getElementById('bottomInput');
const convListEl     = document.getElementById('conversationList');
const newChatBtnEl   = document.getElementById('newChatBtn');
const docListEl      = document.getElementById('documentList');
const uploadBtnEl    = document.getElementById('uploadBtn');
const fileInputEl    = document.getElementById('fileInput');
const docCountEl     = document.getElementById('docCount');
const inputNoteEl    = document.getElementById('inputNote');
const sidebarEl      = document.getElementById('sidebar');
const sidebarOpenEl  = document.getElementById('sidebarOpen');
const sidebarCloseEl = document.getElementById('sidebarClose');
const topbarEl       = document.getElementById('topbar');
const statusDotEl    = document.getElementById('sidebarStatus');
const statusTextEl   = document.getElementById('sidebarStatusText');
const welcomeUploadEl = document.getElementById('welcomeUploadBtn');
const chatUploadEl   = document.getElementById('chatUploadBtn');
const modeChatBtn    = document.getElementById('modeChatBtn');
const modeEvalBtn    = document.getElementById('modeEvalBtn');
const modeEmailBtn   = document.getElementById('modeEmailBtn');
const modeQABtn      = document.getElementById('modeQABtn');
const modeLabelEl    = document.getElementById('modeLabel');
const chatModeLabelEl = document.getElementById('chatModeLabel');

marked.setOptions({ breaks: true, gfm: true });

// -- mode toggle --
// chat mode = ask questions about SOPs
// evaluate mode = paste case data json and get SOP evaluation

function setMode(mode) {
  currentMode = mode;
  modeChatBtn.classList.toggle('active', mode === 'chat');
  modeEvalBtn.classList.toggle('active', mode === 'evaluate');
  modeEmailBtn.classList.toggle('active', mode === 'email');
  modeQABtn.classList.toggle('active', mode === 'qa');

  const labels = { chat: 'Chat', evaluate: 'Evaluate', email: 'Draft Email', qa: 'QA Review' };
  modeLabelEl.textContent = labels[mode] || mode;
  chatModeLabelEl.textContent = labels[mode] || mode;

  const placeholders = {
    chat: ['Ask about SOPs, policies, or processes...', 'Ask anything...'],
    evaluate: ['Paste case data (JSON) to evaluate against SOP...', 'Paste case data or ask about a specific policy...'],
    email: ['Paste email request JSON or describe the decision to communicate...', 'Describe the UW decision to draft an email for...'],
    qa: ['Paste QA case data (JSON) for underwriting review...', 'Paste QA indicators for review...'],
  };
  const ph = placeholders[mode] || placeholders.chat;
  userInputEl.placeholder = ph[0];
  chatInputEl.placeholder = ph[1];

  // re-render the conversation list filtered to this mode
  renderConvList();

  // if current active conversation doesn't belong to this mode, switch to the most recent one that does or create new
  const activeConv = getActive();
  if (activeConv && (activeConv.mode || 'chat') !== mode) {
    const modeConvs = conversations.filter(c => (c.mode || 'chat') === mode);
    if (modeConvs.length > 0) {
      switchConversation(modeConvs[0].id);
    } else {
      newConversation();
    }
  }
}

modeChatBtn.addEventListener('click', () => setMode('chat'));
modeEvalBtn.addEventListener('click', () => setMode('evaluate'));
modeEmailBtn.addEventListener('click', () => setMode('email'));
modeQABtn.addEventListener('click', () => setMode('qa'));

// -- sidebar open/close --

function setSidebar(open) {
  if (open) {
    sidebarEl.classList.remove('collapsed');
    topbarEl.classList.add('hidden');
  } else {
    sidebarEl.classList.add('collapsed');
    topbarEl.classList.remove('hidden');
  }
}

sidebarOpenEl.addEventListener('click', () => setSidebar(true));
sidebarCloseEl.addEventListener('click', () => setSidebar(false));

// -- check if the backend + AI is online --

async function checkStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/status`);
    const data = await res.json();
    if (data.ai_available) {
      statusDotEl.className = 'status-dot online';
      statusTextEl.textContent = data.model;
    } else {
      statusDotEl.className = 'status-dot offline';
      statusTextEl.textContent = 'AI unavailable';
    }
    if (data.documents) renderDocumentList(data.documents);
  } catch {
    statusDotEl.className = 'status-dot offline';
    statusTextEl.textContent = 'Server offline';
  }
}

// -- document list + upload handling --

function renderDocumentList(documents) {
  docListEl.innerHTML = '';
  documents.forEach(doc => {
    const el = document.createElement('div');
    el.className = 'doc-item';
    el.innerHTML = `
      <div class="doc-info">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M7 1H3a1 1 0 00-1 1v8a1 1 0 001 1h6a1 1 0 001-1V4L7 1z" stroke="#4a4a4a" stroke-width="1" fill="none"/>
          <path d="M7 1v3h3" stroke="#4a4a4a" stroke-width="1" fill="none"/>
        </svg>
        <span class="doc-name" title="${doc.filename}">${doc.name}</span>
      </div>
      <button class="doc-delete" title="Remove" data-filename="${doc.filename}">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
        </svg>
      </button>
    `;
    docListEl.appendChild(el);
  });

  // hook up delete buttons
  docListEl.querySelectorAll('.doc-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm(`Remove "${btn.dataset.filename}"?`)) return;
      try {
        const res = await fetch(`${API_BASE}/api/documents/${btn.dataset.filename}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.documents) renderDocumentList(data.documents);
      } catch (err) { console.error(err); }
    });
  });

  const n = documents.length;
  docCountEl.textContent = n === 0 ? 'No documents' : `${n} doc${n > 1 ? 's' : ''} loaded`;
  inputNoteEl.textContent = n === 0
    ? 'Upload SOPs and documents to get started'
    : `Grounded in ${n} document${n > 1 ? 's' : ''}`;
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  uploadBtnEl.disabled = true;
  uploadBtnEl.textContent = 'Uploading...';
  try {
    const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Upload failed'); return; }
    if (data.documents) renderDocumentList(data.documents);
    setSidebar(true);
  } catch (err) { alert('Upload failed: ' + err.message); }
  finally {
    uploadBtnEl.disabled = false;
    uploadBtnEl.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path d="M7 10V2M3 6l4-4 4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M1 10v2a1 1 0 001 1h10a1 1 0 001-1v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      Upload document
    `;
  }
}

function triggerUpload() { fileInputEl.click(); }
uploadBtnEl.addEventListener('click', triggerUpload);
welcomeUploadEl.addEventListener('click', triggerUpload);
chatUploadEl.addEventListener('click', triggerUpload);
fileInputEl.addEventListener('change', () => {
  if (fileInputEl.files.length > 0) { uploadFile(fileInputEl.files[0]); fileInputEl.value = ''; }
});

// -- conversation management --
// everything stored in localStorage so chats survive page refresh

function save() { localStorage.setItem('sl_convos', JSON.stringify(conversations)); }
function getActive() { return conversations.find(c => c.id === activeId) || null; }

function newConversation() {
  const id = `c_${Date.now()}`;
  conversations.unshift({ id, title: 'New conversation', messages: [], ts: Date.now(), mode: currentMode });
  activeId = id;
  save();
  renderConvList();
  renderMessages([]);
  showWelcome();
  userInputEl.focus();
}

function deleteConversation(id) {
  conversations = conversations.filter(c => c.id !== id);
  if (activeId === id) {
    // find the next conversation in the same mode
    const modeConvs = conversations.filter(c => (c.mode || 'chat') === currentMode);
    if (modeConvs.length > 0) {
      activeId = modeConvs[0].id;
      const conv = getActive();
      if (conv && conv.messages.length > 0) { hideWelcome(); renderMessages(conv.messages); }
      else { showWelcome(); renderMessages([]); }
    } else {
      activeId = null;
      newConversation();
      return;
    }
  }
  save();
  renderConvList();
}

function switchConversation(id) {
  activeId = id;
  renderConvList();
  const conv = getActive();
  if (!conv) return;
  if (conv.messages.length === 0) { showWelcome(); renderMessages([]); }
  else { hideWelcome(); renderMessages(conv.messages); scrollToBottom(); }
}

function renderConvList() {
  convListEl.innerHTML = '';

  // update the section label to match the current mode
  const modeLabels = { chat: 'Chats', evaluate: 'Evaluations', email: 'Email Drafts', qa: 'QA Reviews' };
  const sectionLabel = document.querySelector('.sidebar-section:first-of-type .sidebar-label');
  if (sectionLabel) sectionLabel.textContent = modeLabels[currentMode] || 'Chats';

  // filter conversations to only show those matching the current mode
  const filtered = conversations.filter(conv => {
    // conversations created before mode tracking default to 'chat'
    const convMode = conv.mode || 'chat';
    return convMode === currentMode;
  });

  if (filtered.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'conv-empty';
    empty.textContent = `No ${(modeLabels[currentMode] || 'chats').toLowerCase()} yet`;
    convListEl.appendChild(empty);
    return;
  }

  filtered.forEach(conv => {
    const el = document.createElement('div');
    el.className = `conv-item${conv.id === activeId ? ' active' : ''}`;

    const title = document.createElement('span');
    title.className = 'conv-title';
    title.textContent = conv.title;
    title.title = conv.title;

    const del = document.createElement('button');
    del.className = 'conv-delete';
    del.title = 'Delete chat';
    del.innerHTML = `<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>`;
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteConversation(conv.id);
    });

    el.appendChild(title);
    el.appendChild(del);
    el.addEventListener('click', () => {
      // restore the mode this conversation was created in
      if (conv.mode && conv.mode !== currentMode) setMode(conv.mode);
      switchConversation(conv.id);
    });
    convListEl.appendChild(el);
  });
}

function updateTitle(id, msg) {
  const c = conversations.find(x => x.id === id);
  if (c) { c.title = msg.length > 44 ? msg.slice(0, 44) + '\u2026' : msg; save(); renderConvList(); }
}

// -- welcome screen vs chat --

function showWelcome() {
  welcomeEl.style.display = 'flex';
  bottomInputEl.classList.add('hidden');
}

function hideWelcome() {
  welcomeEl.style.display = 'none';
  bottomInputEl.classList.remove('hidden');
  chatInputEl.focus();
}

// -- rendering messages --

function renderMessages(msgs) {
  messagesEl.innerHTML = '';
  msgs.forEach(m => appendMessage(m.role, m.content, false));
  scrollToBottom();
}

function appendMessage(role, content, streaming = false) {
  const el = document.createElement('div');
  el.className = `message ${role}`;

  if (role === 'user') {
    const c = document.createElement('div');
    c.className = 'msg-content';
    c.textContent = content;
    el.appendChild(c);
    messagesEl.appendChild(el);
    return null;
  }

  // assistant message — has avatar + rendered markdown
  const hdr = document.createElement('div');
  hdr.className = 'msg-header';
  hdr.innerHTML = `
    <div class="msg-avatar">S</div>
    <span class="msg-sender">Singlife AI Ops</span>
  `;

  const body = document.createElement('div');
  body.className = 'msg-body';

  if (streaming) {
    const dots = document.createElement('div');
    dots.className = 'loading-dots';
    dots.innerHTML = '<span></span><span></span><span></span>';
    body.appendChild(dots);
  } else {
    body.innerHTML = marked.parse(content || '');
  }

  el.appendChild(hdr);
  el.appendChild(body);

  // add export bar for non-streaming assistant messages
  if (!streaming && content) {
    const exportBar = document.createElement('div');
    exportBar.className = 'msg-export-bar';

    const conv = getActive();
    const msgMode = conv?.mode || currentMode;

    exportBar.innerHTML = `
      <span class="export-label">Export</span>
      <button class="export-btn" data-format="json" title="Download as JSON">JSON</button>
      <button class="export-btn" data-format="csv" title="Download as CSV">CSV</button>
      <button class="export-btn" data-format="excel" title="Download as Excel">Excel</button>
    `;

    exportBar.querySelectorAll('.export-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const fmt = btn.dataset.format;
        if (fmt === 'json') exportAsJson(content, msgMode);
        else if (fmt === 'csv') exportAsCsv(content, msgMode);
        else if (fmt === 'excel') exportAsExcel(content, msgMode);
      });
    });

    el.appendChild(exportBar);
  }

  messagesEl.appendChild(el);
  return streaming ? body : null;
}

// -- sending messages --
// handles both chat and evaluate modes, streams response via SSE

async function sendMessage(text) {
  if (isStreaming || !text.trim()) return;
  if (!activeId) newConversation();

  const conv = getActive();
  if (!conv) return;

  const userText = text.trim();
  hideWelcome();

  conv.messages.push({ role: 'user', content: userText });
  if (conv.messages.length === 1) updateTitle(conv.id, userText);
  save();

  appendMessage('user', userText);
  scrollToBottom();

  // disable inputs while streaming
  userInputEl.value = '';
  chatInputEl.value = '';
  autoResize(userInputEl);
  autoResize(chatInputEl);
  sendBtnEl.disabled = true;
  chatSendBtnEl.disabled = true;
  isStreaming = true;

  const bodyEl = appendMessage('assistant', '', true);
  scrollToBottom();

  let fullText = '';
  let first = true;

  try {
    // pick endpoint based on mode
    let endpoint = `${API_BASE}/api/chat`;
    let payload = { messages: conv.messages, mode: currentMode };

    if (currentMode === 'evaluate') {
      let caseData = userText;
      try { caseData = JSON.parse(userText); } catch {}
      endpoint = `${API_BASE}/api/evaluate`;
      payload = { caseData, messages: conv.messages.slice(0, -1) };
    } else if (currentMode === 'email') {
      let emailData = { decision_type: 'Decline', customer_name: '[Customer Name]', outcome_summary: userText };
      try { emailData = JSON.parse(userText); } catch {}
      endpoint = `${API_BASE}/api/generate-email`;
      payload = { emailData, messages: conv.messages.slice(0, -1) };
    } else if (currentMode === 'qa') {
      let qaData = userText;
      try { qaData = JSON.parse(userText); } catch {}
      endpoint = `${API_BASE}/api/qa-review`;
      payload = { qaData, messages: conv.messages.slice(0, -1) };
    }

    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: 'Server error' }));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    if (!resp.body) throw new Error('No response body');

    // read the SSE stream chunk by chunk
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const p = line.slice(6).trim();
        if (p === '[DONE]') continue;
        try {
          const parsed = JSON.parse(p);
          if (parsed.text) {
            if (first) { bodyEl.innerHTML = ''; first = false; }
            fullText += parsed.text;
            bodyEl.innerHTML = marked.parse(fullText) + '<span class="typing-cursor"></span>';
            scrollToBottom();
          }
        } catch {}
      }
    }
    if (bodyEl) bodyEl.innerHTML = marked.parse(fullText || '*(no response)*');
    if (!fullText) fullText = '*(no response)*';
  } catch (err) {
    fullText = `**Error:** ${err.message}`;
    if (bodyEl) bodyEl.innerHTML = marked.parse(fullText);
  }

  conv.messages.push({ role: 'assistant', content: fullText });
  save();
  isStreaming = false;

  // add export bar to the streamed message
  const lastMsg = messagesEl.querySelector('.message.assistant:last-child');
  if (lastMsg && fullText && !fullText.startsWith('**Error')) {
    const exportBar = document.createElement('div');
    exportBar.className = 'msg-export-bar';
    const msgMode = conv.mode || currentMode;
    exportBar.innerHTML = `
      <span class="export-label">Export</span>
      <button class="export-btn" data-format="json" title="Download as JSON">JSON</button>
      <button class="export-btn" data-format="csv" title="Download as CSV">CSV</button>
      <button class="export-btn" data-format="excel" title="Download as Excel">Excel</button>
    `;
    exportBar.querySelectorAll('.export-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const fmt = btn.dataset.format;
        if (fmt === 'json') exportAsJson(fullText, msgMode);
        else if (fmt === 'csv') exportAsCsv(fullText, msgMode);
        else if (fmt === 'excel') exportAsExcel(fullText, msgMode);
      });
    });
    lastMsg.appendChild(exportBar);
  }

  scrollToBottom();
  chatInputEl.focus();
}

// -- export functions --

function getExportFilename(mode) {
  const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
  const prefixes = { chat: 'chat', evaluate: 'sop-evaluation', email: 'email-draft', qa: 'qa-review' };
  return `${prefixes[mode] || 'export'}_${ts}`;
}

function extractJsonFromMarkdown(text) {
  // try to find JSON blocks in the markdown response
  const jsonBlocks = [];
  const regex = /```json\s*\n([\s\S]*?)```/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    try { jsonBlocks.push(JSON.parse(match[1].trim())); } catch {}
  }
  return jsonBlocks;
}

function responseToStructured(content, mode) {
  // try to extract structured data from the response
  const jsonBlocks = extractJsonFromMarkdown(content);

  if (jsonBlocks.length > 0) {
    // merge all JSON blocks
    return jsonBlocks.length === 1 ? jsonBlocks[0] : jsonBlocks;
  }

  // fallback: return as text object
  return { mode, content, exported_at: new Date().toISOString() };
}

function flattenForCsv(data) {
  // convert structured data to flat rows for CSV/Excel
  if (Array.isArray(data)) {
    if (data.length === 0) return [{ content: '(empty)' }];
    // if array of objects, use as-is
    if (typeof data[0] === 'object') return data.map(item => flattenObj(item));
    return data.map((item, i) => ({ index: i, value: String(item) }));
  }

  // if it has sop_rule_evaluation array, use that as the main table
  if (data.sop_rule_evaluation) {
    const steps = data.sop_rule_evaluation.map(step => flattenObj(step));
    // add summary row
    steps.push({
      step_id: '---',
      description: 'OVERALL DECISION',
      status: data.overall_decision || '',
      finding: data.ops_outcome || '',
      confidence: '',
      decision_impact: data.automation_trigger || '',
      recommended_action: (data.steps_failed || []).join(', '),
    });
    return steps;
  }

  // if it has breakdown (QA scoring)
  if (data.breakdown) {
    return data.breakdown.map(([indicator, points, detail]) => ({
      indicator, points, detail
    }));
  }

  // generic object: one row per key
  return Object.entries(flattenObj(data)).map(([key, value]) => ({ field: key, value: String(value) }));
}

function flattenObj(obj, prefix = '') {
  const result = {};
  for (const [key, val] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      Object.assign(result, flattenObj(val, fullKey));
    } else if (Array.isArray(val)) {
      result[fullKey] = val.join('; ');
    } else {
      result[fullKey] = val;
    }
  }
  return result;
}

function exportAsJson(content, mode) {
  const data = responseToStructured(content, mode);
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
  downloadBlob(blob, getExportFilename(mode) + '.json');
}

function exportAsCsv(content, mode) {
  const data = responseToStructured(content, mode);
  const rows = flattenForCsv(data);
  if (!rows.length) return;

  const headers = Object.keys(rows[0]);
  const csvLines = [headers.join(',')];
  for (const row of rows) {
    csvLines.push(headers.map(h => {
      const val = String(row[h] ?? '');
      return val.includes(',') || val.includes('"') || val.includes('\n')
        ? `"${val.replace(/"/g, '""')}"` : val;
    }).join(','));
  }
  // UTF-8 BOM so Excel correctly reads special characters (em dash, arrows, etc.)
  const bom = '\uFEFF';
  const blob = new Blob([bom + csvLines.join('\n')], { type: 'text/csv;charset=utf-8' });
  downloadBlob(blob, getExportFilename(mode) + '.csv');
}

function exportAsExcel(content, mode) {
  if (typeof XLSX === 'undefined') {
    alert('Excel export library not loaded. Try JSON or CSV instead.');
    return;
  }
  const data = responseToStructured(content, mode);
  const rows = flattenForCsv(data);
  const ws = XLSX.utils.json_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, mode);
  XLSX.writeFile(wb, getExportFilename(mode) + '.xlsx');
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// -- helpers --

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function scrollToBottom() {
  requestAnimationFrame(() => { chatContainer.scrollTop = chatContainer.scrollHeight; });
}

// -- wire up event listeners --

userInputEl.addEventListener('input', () => {
  autoResize(userInputEl);
  sendBtnEl.disabled = userInputEl.value.trim().length === 0 || isStreaming;
});
userInputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!sendBtnEl.disabled) sendMessage(userInputEl.value); }
});
sendBtnEl.addEventListener('click', () => sendMessage(userInputEl.value));

chatInputEl.addEventListener('input', () => {
  autoResize(chatInputEl);
  chatSendBtnEl.disabled = chatInputEl.value.trim().length === 0 || isStreaming;
});
chatInputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!chatSendBtnEl.disabled) sendMessage(chatInputEl.value); }
});
chatSendBtnEl.addEventListener('click', () => sendMessage(chatInputEl.value));

newChatBtnEl.addEventListener('click', () => newConversation());

// -- init on page load --

(function init() {
  checkStatus();
  setSidebar(false);

  if (conversations.length === 0) {
    newConversation();
  } else {
    activeId = conversations[0].id;
    renderConvList();
    const conv = getActive();
    if (conv && conv.messages.length > 0) { hideWelcome(); renderMessages(conv.messages); }
    else showWelcome();
  }

  userInputEl.focus();
})();
