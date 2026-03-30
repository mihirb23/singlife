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

  const label = mode === 'chat' ? 'Chat' : 'Evaluate';
  modeLabelEl.textContent = label;
  chatModeLabelEl.textContent = label;

  if (mode === 'chat') {
    userInputEl.placeholder = 'Ask about SOPs, policies, or processes...';
    chatInputEl.placeholder = 'Ask anything...';
  } else {
    userInputEl.placeholder = 'Paste case data (JSON or text) to evaluate against SOP...';
    chatInputEl.placeholder = 'Paste case data or ask about a specific policy...';
  }
}

modeChatBtn.addEventListener('click', () => setMode('chat'));
modeEvalBtn.addEventListener('click', () => setMode('evaluate'));

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
  conversations.unshift({ id, title: 'New conversation', messages: [], ts: Date.now() });
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
    if (conversations.length > 0) {
      activeId = conversations[0].id;
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
  conversations.forEach(conv => {
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
    el.addEventListener('click', () => switchConversation(conv.id));
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

    // in evaluate mode, try to parse input as JSON for the case data
    if (currentMode === 'evaluate') {
      let caseData = userText;
      try {
        caseData = JSON.parse(userText);
      } catch {
        // not valid json, just send as plain text — claude can handle it
      }
      endpoint = `${API_BASE}/api/evaluate`;
      payload = { caseData, messages: conv.messages.slice(0, -1) };
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
  scrollToBottom();
  chatInputEl.focus();
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
