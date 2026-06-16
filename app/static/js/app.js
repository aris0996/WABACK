const pageRoot = document.querySelector('.app-shell');
const state = {
  config: {},
  contacts: [],
  activeContact: null,
  view: pageRoot?.dataset.page || 'overview',
  contactLimit: 50,
  contactOffset: 0,
  contactTotal: 0,
};

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pretty = (value) => JSON.stringify(value, null, 2);
let logTimer = null;

function toast(message, type = 'ok') {
  const box = $('#toast');
  if (!box) return;
  box.textContent = message;
  box.className = `toast ${type}`;
  setTimeout(() => box.classList.add('hidden'), 4200);
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const data = await res.json().catch(() => ({ ok: false, error: 'Invalid response' }));
  if (!res.ok || data.ok === false) throw new Error(data.error || 'Request failed');
  return data;
}

async function guarded(action, successMessage = '') {
  try {
    const result = await action();
    if (successMessage) toast(successMessage);
    return result;
  } catch (err) {
    toast(err.message, 'error');
    throw err;
  }
}

async function refreshCurrent() {
  if (state.view === 'overview') await guarded(loadOverview);
  if (state.view === 'contacts') await guarded(loadContacts);
  if (state.view === 'settings') renderSettings();
  if (state.view === 'diagnostics') await guarded(loadDiagnostics);
  if (state.view === 'ai_logs') await guarded(loadAiLogs);
  if (state.view === 'logs') await guarded(loadLogs);
}

async function loadConfig() {
  const data = await api('/api/config');
  state.config = data.config;
  if (state.view === 'settings') renderSettings();
}

function statusValue(value) {
  return value === 'true' ? '<span class="status on">On</span>' : '<span class="status off">Off</span>';
}

async function loadOverview() {
  const data = await api('/api/overview');
  state.config = data.config;
  const cards = [
    ['Chats', data.stats.contacts, 'Direct chat dan grup tersimpan'],
    ['Groups', data.stats.groups, 'Grup WAHA yang tersinkron'],
    ['Messages', data.stats.messages, 'Total pesan masuk dan keluar'],
    ['Global Auto Reply', statusValue(data.config.global_auto_reply), 'Master switch balasan otomatis'],
    ['Model Chatbot', data.config.chatbot_model, 'Model custom dari Modelfile'],
    ['Context Limit', data.config.history_context_limit, 'Jumlah history terbaru untuk prompt'],
  ];
  $('#overview-cards').innerHTML = cards.map(([label, value, hint]) => `
    <div class="stat">
      <span>${esc(label)}</span>
      <strong>${typeof value === 'string' && value.includes('<span') ? value : esc(value)}</strong>
      <small>${esc(hint)}</small>
    </div>`).join('');
  $('#waha-webhook-url').value = `${window.location.origin}/webhook/waha`;
  $('#github-webhook-url').value = `${window.location.origin}/webhook/github`;
}

async function testService(kind, target = '#settings-result') {
  const path = kind === 'waha' ? '/api/test-waha' : '/api/test-ollama';
  const label = kind === 'waha' ? 'WAHA' : 'Ollama';
  const box = $(target);
  if (box) box.textContent = `Testing ${label}...`;
  const data = await guarded(() => api(path, { method: 'POST', body: '{}' }), `${label} connection OK`);
  if (box) box.textContent = pretty(data);
}

async function loadContacts() {
  const q = encodeURIComponent($('#contact-search')?.value || '');
  const type = encodeURIComponent($('#chat-type-filter')?.value || '');
  const auto = encodeURIComponent($('#chat-auto-filter')?.value || '');
  const data = await api(`/api/contacts?q=${q}&type=${type}&auto=${auto}&limit=${state.contactLimit}&offset=${state.contactOffset}`);
  state.contacts = data.contacts;
  state.contactTotal = data.total || 0;
  if (!data.contacts.length) {
    $('#contacts-table').innerHTML = `<tbody><tr><td class="empty-state">Belum ada chat. Sync WAHA atau arahkan webhook WAHA event <code>message.any</code> ke <code>${esc(window.location.origin)}/webhook/waha</code>.</td></tr></tbody>`;
    renderContactPagination();
    return;
  }
  $('#contacts-table').innerHTML = `
    <thead><tr><th>Chat</th><th>Tipe</th><th>Status</th><th>Pesan</th><th>Terakhir</th><th>Aksi</th></tr></thead>
    <tbody>${data.contacts.map(c => `
      <tr>
        <td><strong>${esc(c.display_name || c.wa_number)}</strong><small>${esc(c.chat_id || c.wa_number)}</small></td>
        <td><span class="status ${c.chat_type === 'group' ? 'warn' : 'on'}">${esc(c.chat_type || 'direct')}</span></td>
        <td><div class="status-stack">
          ${c.auto_reply_enabled ? '<span class="status on">Auto Reply</span>' : '<span class="status off">Auto Off</span>'}
          ${c.ai_blocked ? '<span class="status bad">AI Blocked</span>' : '<span class="status on">AI Allowed</span>'}
        </div></td>
        <td><strong>${c.message_count || 0}</strong></td>
        <td>${esc(c.last_chat_at || '-')}</td>
        <td><div class="mini-actions">
          <button onclick="openContact(${c.id})">Detail</button>
          <button class="secondary" onclick="postAndReload('/api/contacts/${c.id}/toggle-auto-reply')">Toggle</button>
          <button class="${c.ai_blocked ? 'secondary' : 'danger'}" onclick="postAndReload('/api/contacts/${c.id}/${c.ai_blocked ? 'unblock-ai' : 'block-ai'}')">${c.ai_blocked ? 'Unblock' : 'Block'}</button>
        </div></td>
      </tr>`).join('')}</tbody>`;
  renderContactPagination();
}

function renderContactPagination() {
  const box = $('#contacts-pagination');
  if (!box) return;
  const start = state.contactTotal ? state.contactOffset + 1 : 0;
  const end = Math.min(state.contactOffset + state.contactLimit, state.contactTotal);
  box.innerHTML = `
    <span>Menampilkan ${start}-${end} dari ${state.contactTotal} chat</span>
    <div class="mini-actions">
      <button class="secondary" ${state.contactOffset <= 0 ? 'disabled' : ''} onclick="changeContactPage(-1)">Prev</button>
      <button class="secondary" ${end >= state.contactTotal ? 'disabled' : ''} onclick="changeContactPage(1)">Next</button>
    </div>`;
}

async function changeContactPage(direction) {
  state.contactOffset = Math.max(0, state.contactOffset + direction * state.contactLimit);
  await guarded(loadContacts);
}

async function addContact() {
  const wa_number = $('#new-contact-number').value.trim();
  const display_name = $('#new-contact-name').value.trim();
  const data = await guarded(() => api('/api/contacts', { method: 'POST', body: JSON.stringify({ wa_number, display_name }) }), 'Chat ditambahkan');
  $('#new-contact-number').value = '';
  $('#new-contact-name').value = '';
  await loadContacts();
  await openContact(data.contact_id);
}

async function syncWahaContacts() {
  const box = $('#contact-sync-result');
  if (box) {
    box.classList.remove('hidden');
    box.textContent = 'Sync chats dari WAHA...';
  }
  const data = await guarded(() => api('/api/contacts/sync-waha', { method: 'POST', body: JSON.stringify({ limit: 300, max_total: 3000 }) }), 'Sync chats WAHA selesai');
  if (box) box.textContent = pretty(data.result);
  await loadContacts();
}

async function postAndReload(path) {
  await guarded(() => api(path, { method: 'POST', body: '{}' }), 'Perubahan tersimpan');
  await loadContacts();
  if (state.activeContact) await openContact(state.activeContact);
}

async function openContact(id) {
  state.activeContact = id;
  const data = await guarded(() => api(`/api/contacts/${id}`));
  const c = data.contact;
  const counts = data.counts || {};
  $('#contact-drawer')?.classList.remove('hidden');
  $('#contact-detail').innerHTML = `
    <div class="detail-title">
      <div>
        <h3>${esc(c.display_name || c.wa_number)}</h3>
        <p>${esc(c.chat_id || c.wa_number)} · ${esc(c.chat_type || 'direct')} · ${counts.total_messages || 0} pesan lokal</p>
      </div>
      <div class="mini-actions">
        <button class="secondary" onclick="postAndReload('/api/contacts/${c.id}/toggle-auto-reply')">${c.auto_reply_enabled ? 'Matikan Auto Reply' : 'Aktifkan Auto Reply'}</button>
        <button class="${c.ai_blocked ? 'secondary' : 'danger'}" onclick="postAndReload('/api/contacts/${c.id}/${c.ai_blocked ? 'unblock-ai' : 'block-ai'}')">${c.ai_blocked ? 'Unblock AI' : 'Block AI'}</button>
      </div>
      <button class="secondary" onclick="closeContactDrawer()">Tutup</button>
    </div>
    <div class="tabs">
      <button class="tab active" onclick="showContactTab('overview')">Overview</button>
      <button class="tab" onclick="showContactTab('history')">History</button>
      <button class="tab" onclick="showContactTab('ai')">Auto Reply</button>
      <button class="tab" onclick="showContactTab('send')">Send Message</button>
      <button class="tab" onclick="showContactTab('debug')">Debug</button>
    </div>
    <div class="contact-tab active" data-tab="overview">
      <div class="stats-grid detail-stats">
        <div class="stat"><span>Pesan Lokal</span><strong>${counts.total_messages || 0}</strong><small>In ${counts.inbound_messages || 0} · Out ${counts.outbound_messages || 0}</small></div>
        <div class="stat"><span>Auto Reply</span><strong>${c.auto_reply_enabled ? 'On' : 'Off'}</strong><small>Status balasan chat ini</small></div>
        <div class="stat"><span>AI Block</span><strong>${c.ai_blocked ? 'Blocked' : 'Allowed'}</strong><small>Kontrol AI per chat</small></div>
        <div class="stat"><span>Trigger Grup</span><strong>${esc((c.trigger_keywords || '').split(/\\s+/).filter(Boolean).length)}</strong><small>Dipakai hanya untuk group</small></div>
      </div>
    </div>
    <div class="contact-tab" data-tab="history">
      <div class="panel inset">
        <h4>WAHA History</h4>
        <p class="note">Sync mengambil history terbaru berdasarkan chat id asli WAHA tanpa duplikat.</p>
        <button onclick="syncWahaHistory(${id})">Sync History WAHA</button>
        <pre id="history-sync-result" class="code-box small hidden"></pre>
        <div class="chat-box">
          ${data.messages.length ? data.messages.map(m => `<div class="msg ${m.direction}"><small>#${m.id} ${esc(m.direction)} ${esc(m.sender_name || '')} - ${esc(m.created_at)}</small>${esc(m.message)}</div>`).join('') : '<div class="empty-state">Belum ada riwayat chat.</div>'}
        </div>
      </div>
    </div>
    <div class="contact-tab" data-tab="ai">
      <div class="panel inset">
        <h4>Auto Reply</h4>
        <label>Nama display<input id="detail-name" value="${esc(c.display_name || '')}"></label>
        <label>Auto Reply<select id="detail-auto-reply"><option value="true" ${c.auto_reply_enabled ? 'selected' : ''}>On</option><option value="false" ${!c.auto_reply_enabled ? 'selected' : ''}>Off</option></select></label>
        <label>AI Block<select id="detail-ai-blocked"><option value="false" ${!c.ai_blocked ? 'selected' : ''}>Allowed</option><option value="true" ${c.ai_blocked ? 'selected' : ''}>Blocked</option></select></label>
        <label>Trigger keyword grup<textarea id="detail-trigger-keywords" placeholder="Contoh: bot ai halo">${esc(c.trigger_keywords || '')}</textarea></label>
        <p class="note">Direct chat tidak perlu trigger. Grup hanya dibalas jika pesan mengandung salah satu trigger keyword.</p>
        <button onclick="saveContactSettings(${id})">Simpan pengaturan</button>
      </div>
    </div>
    <div class="contact-tab" data-tab="send">
      <div class="panel inset">
        <h4>Kirim Pesan</h4>
        <label>Pesan manual<textarea id="manual-message" placeholder="Tulis pesan untuk dikirim via WAHA"></textarea></label>
        <button onclick="sendManual(${c.id})">Kirim via WAHA</button>
      </div>
    </div>
    <div class="contact-tab" data-tab="debug">
      <div class="panel inset">
        <h4>Debug Chat</h4>
        <button class="secondary" onclick="loadReplyDebug(${id})">Cek Status Auto Reply</button>
        <pre id="reply-debug-result" class="code-box small"></pre>
        <pre class="code-box">${esc(pretty({ contact: c, counts }))}</pre>
      </div>
    </div>`;
}

async function loadReplyDebug(id) {
  const box = $('#reply-debug-result');
  if (box) box.textContent = 'Cek status auto reply...';
  const data = await guarded(() => api(`/api/contacts/${id}/reply-debug`));
  if (box) box.textContent = pretty(data);
}

function closeContactDrawer() {
  $('#contact-drawer')?.classList.add('hidden');
  state.activeContact = null;
}

function showContactTab(tab) {
  document.querySelectorAll('.tab').forEach(btn => btn.classList.toggle('active', btn.textContent.toLowerCase().includes(tab)));
  document.querySelectorAll('.contact-tab').forEach(panel => panel.classList.toggle('active', panel.dataset.tab === tab));
}

async function syncWahaHistory(id) {
  const box = $('#history-sync-result');
  if (box) {
    box.classList.remove('hidden');
    box.textContent = 'Sync history WAHA...';
  }
  const result = await guarded(() => api(`/api/contacts/${id}/sync-waha-history`, { method: 'POST', body: JSON.stringify({ limit: 300 }) }), 'History WAHA tersinkron');
  await openContact(id);
  showContactTab('history');
  const newBox = $('#history-sync-result');
  if (newBox) {
    newBox.classList.remove('hidden');
    newBox.textContent = pretty(result.result);
  }
  await loadContacts();
}

async function saveContactSettings(id) {
  await guarded(() => api(`/api/contacts/${id}/settings`, {
    method: 'POST',
    body: JSON.stringify({
      display_name: $('#detail-name').value,
      auto_reply_enabled: $('#detail-auto-reply').value,
      ai_blocked: $('#detail-ai-blocked').value,
      trigger_keywords: $('#detail-trigger-keywords').value,
    }),
  }), 'Pengaturan chat tersimpan');
  await openContact(id);
  await loadContacts();
}

async function sendManual(contact_id) {
  const message = $('#manual-message').value.trim();
  if (!message) return toast('Pesan masih kosong', 'error');
  await guarded(() => api('/api/send-message', { method: 'POST', body: JSON.stringify({ contact_id, message }) }), 'Pesan terkirim');
  $('#manual-message').value = '';
  await openContact(state.activeContact);
}

function fieldHtml(key, label) {
  const val = state.config[key] || '';
  if (['waha_enabled', 'global_auto_reply', 'default_contact_auto_reply', 'waha_typing_enabled'].includes(key)) {
    return `<label>${label}<select name="${key}"><option value="true" ${val === 'true' ? 'selected' : ''}>On</option><option value="false" ${val !== 'true' ? 'selected' : ''}>Off</option></select></label>`;
  }
  if (key === 'group_trigger_keywords') return `<label>${label}<textarea name="${key}">${esc(val)}</textarea></label>`;
  return `<label>${label}<input name="${key}" value="${esc(val)}"></label>`;
}

function settingsGroup(title, fields) {
  return `<fieldset><legend>${esc(title)}</legend>${fields.map(([key, label]) => fieldHtml(key, label)).join('')}</fieldset>`;
}

function renderSettings() {
  $('#settings-form').innerHTML = [
    settingsGroup('WAHA', [
      ['waha_base_url', 'WAHA Base URL'], ['waha_session', 'WAHA Session'], ['waha_api_key', 'WAHA API Key'], ['waha_enabled', 'Enable WAHA'],
      ['waha_sync_page_size', 'WAHA sync page size'], ['waha_sync_max_contacts', 'WAHA max chats sync'], ['waha_history_sync_limit', 'WAHA history limit per chat'],
    ]),
    settingsGroup('Ollama', [
      ['ollama_base_url', 'Ollama Base URL'], ['chatbot_model', 'Model chatbot'], ['chatbot_num_predict', 'Max token balasan chatbot'],
      ['ollama_keep_alive', 'Ollama keep alive'], ['ollama_request_timeout', 'Ollama request timeout'], ['chatbot_temperature', 'Temperature chatbot'],
    ]),
    settingsGroup('Auto Reply', [
      ['global_auto_reply', 'Global auto reply'], ['reply_delay_seconds', 'Reply delay detik'], ['default_contact_auto_reply', 'Default direct chat auto reply'],
      ['history_context_limit', 'Jumlah history untuk konteks'], ['waha_typing_enabled', 'Tampilkan status mengetik'], ['ai_reply_prefix', 'Format penanda balasan AI'], ['group_trigger_keywords', 'Default trigger keyword grup'],
    ]),
  ].join('');
}

async function saveForm(formSel, resultSel) {
  const data = Object.fromEntries(new FormData($(formSel)).entries());
  const res = await guarded(() => api('/api/config', { method: 'POST', body: JSON.stringify(data) }), 'Konfigurasi tersimpan');
  state.config = res.config;
  $(resultSel).textContent = 'Tersimpan.';
}

async function loadLogs() {
  const filter = ($('#log-filter')?.value || '').toLowerCase().trim();
  const level = $('#log-level')?.value || '';
  const data = await api(`/api/logs?limit=150&q=${encodeURIComponent(filter)}&level=${encodeURIComponent(level)}`);
  $('#logs-table').innerHTML = `<thead><tr><th>Waktu</th><th>Level</th><th>Pesan</th><th>Context</th></tr></thead><tbody>${
    data.logs.length ? data.logs.map(l => `<tr><td>${esc(l.created_at_local || l.created_at)}</td><td><span class="log-level ${esc(l.level.toLowerCase())}">${esc(l.level)}</span></td><td>${esc(l.message)}</td><td><pre>${esc(l.context_json || '')}</pre></td></tr>`).join('') : '<tr><td class="empty-state" colspan="4">Tidak ada log yang cocok.</td></tr>'
  }</tbody>`;
}

async function loadAiLogs() {
  const filter = ($('#ai-log-filter')?.value || '').trim();
  const data = await api(`/api/ai-logs?limit=200&q=${encodeURIComponent(filter)}`);
  $('#ai-logs-table').innerHTML = `<thead><tr><th>Waktu</th><th>Level</th><th>Event</th><th>Context</th></tr></thead><tbody>${
    data.logs.length ? data.logs.map(l => `<tr><td>${esc(l.created_at_local || l.created_at)}</td><td><span class="log-level ${esc(l.level.toLowerCase())}">${esc(l.level)}</span></td><td>${esc(l.message)}</td><td><pre>${esc(l.context_json || '')}</pre></td></tr>`).join('') : '<tr><td class="empty-state" colspan="4">Belum ada AI log yang cocok.</td></tr>'
  }</tbody>`;
}

async function loadDiagnostics() {
  const target = $('#diag-update-result');
  if (!target) return;
  const data = await api('/api/update-status');
  target.textContent = pretty(data.status);
}

function on(selector, event, handler) {
  const el = $(selector);
  if (el) el.addEventListener(event, handler);
}

on('#refresh-current', 'click', () => guarded(refreshCurrent));
on('#contact-search', 'input', () => { state.contactOffset = 0; guarded(loadContacts); });
on('#chat-type-filter', 'change', () => { state.contactOffset = 0; guarded(loadContacts); });
on('#chat-auto-filter', 'change', () => { state.contactOffset = 0; guarded(loadContacts); });
on('#add-contact', 'click', addContact);
on('#sync-waha-contacts', 'click', syncWahaContacts);
on('#save-settings', 'click', () => saveForm('#settings-form', '#settings-result'));
on('#test-waha', 'click', () => testService('waha', '#settings-result'));
on('#test-ollama', 'click', () => testService('ollama', '#settings-result'));
on('#overview-test-waha', 'click', () => testService('waha', '#overview-test-result'));
on('#overview-test-ollama', 'click', () => testService('ollama', '#overview-test-result'));
on('#diag-test-waha', 'click', () => testService('waha', '#diag-service-result'));
on('#diag-test-ollama', 'click', () => testService('ollama', '#diag-service-result'));
on('#diag-update-status', 'click', () => guarded(loadDiagnostics, 'Status Git diperbarui'));
on('#refresh-logs', 'click', () => guarded(loadLogs));
on('#log-level', 'change', () => guarded(loadLogs));
on('#refresh-ai-logs', 'click', () => guarded(loadAiLogs));
on('#ai-log-filter', 'input', () => { clearTimeout(logTimer); logTimer = setTimeout(() => guarded(loadAiLogs), 250); });
on('#log-filter', 'input', () => { clearTimeout(logTimer); logTimer = setTimeout(() => guarded(loadLogs), 250); });

loadConfig().then(refreshCurrent).catch(err => toast(err.message, 'error'));
