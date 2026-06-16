const pageRoot = document.querySelector('.app-shell');
const state = {
  config: {},
  contacts: [],
  activeContact: null,
  view: pageRoot?.dataset.page || 'overview',
  contactLimit: 50,
  contactOffset: 0,
  contactTotal: 0,
  activeJobTimer: null,
};

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pretty = (value) => JSON.stringify(value, null, 2);
let logTimer = null;

function toast(message, type = 'ok') {
  const box = $('#toast');
  box.textContent = message;
  box.className = `toast ${type}`;
  setTimeout(() => box.classList.add('hidden'), 4200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
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
  if (state.view === 'prompts') renderPrompts();
  if (state.view === 'logs') await guarded(loadLogs);
}

async function loadConfig() {
  const data = await api('/api/config');
  state.config = data.config;
  if (state.view === 'settings') renderSettings();
  if (state.view === 'prompts') renderPrompts();
}

function statusValue(value) {
  return value === 'true' ? '<span class="status on">On</span>' : '<span class="status off">Off</span>';
}

async function loadOverview() {
  const data = await api('/api/overview');
  state.config = data.config;
  const cards = [
    ['Kontak', data.stats.contacts, 'Nomor yang sudah pernah masuk atau dibuat manual'],
    ['Pesan', data.stats.messages, 'Total pesan masuk dan keluar'],
    ['Memory', data.stats.memories, 'Kontak yang sudah punya memory final'],
    ['Global Auto Reply', statusValue(data.config.global_auto_reply), 'Master switch balasan otomatis'],
    ['Memory Auto Generate', statusValue(data.config.memory_auto_generate), 'Generate incremental otomatis'],
    ['Model Chatbot', data.config.chatbot_model, 'Harus model hasil Modelfile'],
  ];
  $('#overview-cards').innerHTML = cards.map(([label, value, hint]) => `
    <div class="stat">
      <span>${esc(label)}</span>
      <strong>${typeof value === 'string' && value.includes('<span') ? value : esc(value)}</strong>
      <small>${esc(hint)}</small>
    </div>`).join('');

  const origin = window.location.origin;
  $('#waha-webhook-url').value = `${origin}/webhook/waha`;
  $('#github-webhook-url').value = `${origin}/webhook/github`;
}

async function testService(kind, target = '#settings-result') {
  const path = kind === 'waha' ? '/api/test-waha' : '/api/test-ollama';
  const label = kind === 'waha' ? 'WAHA' : 'Ollama';
  const box = $(target);
  box.textContent = `Testing ${label}...`;
  const data = await guarded(() => api(path, { method: 'POST', body: '{}' }), `${label} connection OK`);
  box.textContent = pretty(data);
}

async function loadContacts() {
  const q = encodeURIComponent($('#contact-search').value || '');
  const data = await api(`/api/contacts?q=${q}&limit=${state.contactLimit}&offset=${state.contactOffset}`);
  state.contacts = data.contacts;
  state.contactTotal = data.total || 0;
  if (!data.contacts.length) {
    $('#contacts-table').innerHTML = `
      <tbody><tr><td class="empty-state">
        Belum ada kontak. Tambahkan nomor manual di atas, atau pastikan webhook WAHA mengarah ke <code>${esc(window.location.origin)}/webhook/waha</code>.
      </td></tr></tbody>`;
    renderContactPagination();
    return;
  }
  $('#contacts-table').innerHTML = `
    <thead><tr><th>Kontak</th><th>Status</th><th>Memory</th><th>Pesan Baru</th><th>Terakhir Chat</th><th>Aksi</th></tr></thead>
    <tbody>${data.contacts.map(c => `
      <tr>
        <td><strong>${esc(c.wa_number)}</strong><small>${esc(c.display_name || 'Tanpa nama')}</small></td>
        <td><div class="status-stack">
          ${c.auto_reply_enabled ? '<span class="status on">Auto Reply</span>' : '<span class="status off">Auto Off</span>'}
          ${c.ai_blocked ? '<span class="status bad">AI Blocked</span>' : '<span class="status on">AI Allowed</span>'}
        </div></td>
        <td>${c.has_memory ? '<span class="status on">Ada</span>' : '<span class="status off">Belum</span>'}</td>
        <td><strong>${c.new_message_count_since_memory}</strong><small>Interval ${c.memory_generate_interval}</small></td>
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
    <span>Menampilkan ${start}-${end} dari ${state.contactTotal} kontak</span>
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
  const data = await guarded(() => api('/api/contacts', {
    method: 'POST',
    body: JSON.stringify({ wa_number, display_name }),
  }), 'Kontak ditambahkan');
  $('#new-contact-number').value = '';
  $('#new-contact-name').value = '';
  await loadContacts();
  await openContact(data.contact_id);
}

async function syncWahaContacts() {
  const box = $('#contact-sync-result');
  if (box) {
    box.classList.remove('hidden');
    box.textContent = 'Sync kontak dari WAHA...';
  }
  const data = await guarded(() => api('/api/contacts/sync-waha', {
    method: 'POST',
    body: JSON.stringify({ limit: 300, max_total: 3000 }),
  }), 'Sync kontak WAHA selesai');
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
  const memory = data.memory ? JSON.parse(data.memory.memory_json) : {};
  $('#contact-drawer')?.classList.remove('hidden');
  $('#contact-detail').innerHTML = `
    <div class="detail-title">
      <div>
        <h3>${esc(c.wa_number)}</h3>
        <p>${esc(c.display_name || 'tanpa nama')} · ${counts.total_messages || 0} pesan lokal</p>
      </div>
      <div class="mini-actions">
        <button class="secondary" onclick="postAndReload('/api/contacts/${c.id}/toggle-auto-reply')">${c.auto_reply_enabled ? 'Matikan Auto Reply' : 'Aktifkan Auto Reply'}</button>
        <button class="${c.ai_blocked ? 'secondary' : 'danger'}" onclick="postAndReload('/api/contacts/${c.id}/${c.ai_blocked ? 'unblock-ai' : 'block-ai'}')">${c.ai_blocked ? 'Unblock AI' : 'Block AI'}</button>
      </div>
      <button class="secondary" onclick="closeContactDrawer()">Tutup</button>
    </div>
    <div class="tabs">
      <button class="tab active" onclick="showContactTab('overview')">Overview</button>
      <button class="tab" onclick="showContactTab('waha')">WAHA History</button>
      <button class="tab" onclick="showContactTab('ai')">AI & Auto Reply</button>
      <button class="tab" onclick="showContactTab('memory')">Memory</button>
      <button class="tab" onclick="showContactTab('messages')">Messages</button>
      <button class="tab" onclick="showContactTab('debug')">Debug</button>
    </div>
    <div class="contact-tab active" data-tab="overview">
      <div class="stats-grid detail-stats">
      <div class="stat"><span>Pesan Lokal</span><strong>${counts.total_messages || 0}</strong><small>In ${counts.inbound_messages || 0} · Out ${counts.outbound_messages || 0}</small></div>
      <div class="stat"><span>Auto Reply</span><strong>${c.auto_reply_enabled ? 'On' : 'Off'}</strong><small>Status balasan untuk kontak ini</small></div>
      <div class="stat"><span>AI Block</span><strong>${c.ai_blocked ? 'Blocked' : 'Allowed'}</strong><small>Kontrol AI per kontak</small></div>
      <div class="stat"><span>Memory Baru</span><strong>${c.new_message_count_since_memory}/${c.memory_generate_interval}</strong><small>Checkpoint #${c.last_memory_message_id}</small></div>
      </div>
    </div>
    <div class="contact-tab" data-tab="ai">
      <div class="panel inset">
        <h4>Pengaturan AI & Auto Reply</h4>
        <label>Nama display<input id="detail-name" value="${esc(c.display_name || '')}"></label>
        <label>Auto generate memory
          <select id="detail-auto-memory"><option value="true" ${c.memory_auto_generate_enabled ? 'selected' : ''}>On</option><option value="false" ${!c.memory_auto_generate_enabled ? 'selected' : ''}>Off</option></select>
        </label>
        <label>Interval generate<input id="detail-interval" type="number" min="1" value="${c.memory_generate_interval}"></label>
        <div class="actions">
          <button onclick="saveContactSettings(${id})">Simpan kontak</button>
        </div>
      </div>
    </div>
    <div class="contact-tab" data-tab="waha">
      <div class="panel inset">
        <h4>WAHA History</h4>
        <p class="note">Sync history mengambil chat dari WAHA lalu menyimpannya ke database lokal tanpa duplikat.</p>
        <div class="actions">
          <button onclick="syncWahaHistory(${id})">Sync History WAHA</button>
        </div>
        <pre id="history-sync-result" class="code-box small hidden"></pre>
      </div>
    </div>
    <div class="contact-tab" data-tab="messages">
      <div class="panel inset">
        <h4>Kirim Pesan</h4>
        <label>Kirim pesan manual<textarea id="manual-message" placeholder="Tulis pesan untuk dikirim via WAHA"></textarea></label>
        <button onclick="sendManual('${esc(c.wa_number)}')">Kirim via WAHA</button>
      </div>
    </div>
    <div class="contact-tab" data-tab="memory">
      <div class="panel inset">
        <h4>Memory</h4>
        <p class="note">Generate semua akan sync history WAHA terlebih dahulu, lalu membuat memory dari semua pesan lokal.</p>
        <div id="memory-job-status" class="job-status hidden"></div>
        <div class="actions">
          <button onclick="memoryAction(${id}, 'generate-all')">Sync WAHA + Generate Semua</button>
          <button class="secondary" onclick="memoryAction(${id}, 'generate-new')">Generate Pesan Baru</button>
          <button class="danger" onclick="memoryAction(${id}, 'reset')">Reset Memory</button>
        </div>
        <label><textarea id="memory-json" class="memory-editor">${esc(JSON.stringify(memory, null, 2))}</textarea></label>
        <button onclick="saveMemory(${id})">Simpan memory manual</button>
      </div>
    </div>
    <div class="contact-tab active" data-tab="overview">
      <div class="panel inset">
      <h4>Riwayat Chat</h4>
      <div class="chat-box">
        ${data.messages.length ? data.messages.map(m => `<div class="msg ${m.direction}"><small>#${m.id} ${esc(m.direction)} - ${esc(m.created_at)}</small>${esc(m.message)}</div>`).join('') : '<div class="empty-state">Belum ada riwayat chat.</div>'}
      </div>
      </div>
    </div>
    <div class="contact-tab" data-tab="debug">
      <div class="panel inset">
        <h4>Debug Kontak</h4>
        <pre class="code-box">${esc(pretty({ contact: c, counts }))}</pre>
      </div>
    </div>`;
}

function closeContactDrawer() {
  $('#contact-drawer')?.classList.add('hidden');
  state.activeContact = null;
  if (state.activeJobTimer) clearInterval(state.activeJobTimer);
}

function showContactTab(tab) {
  document.querySelectorAll('.tab').forEach(btn => btn.classList.toggle('active', btn.textContent.toLowerCase().includes(tab.split('-')[0])));
  document.querySelectorAll('.contact-tab').forEach(panel => panel.classList.toggle('active', panel.dataset.tab === tab));
}

async function syncWahaHistory(id) {
  const box = $('#history-sync-result');
  if (box) {
    box.classList.remove('hidden');
    box.textContent = 'Sync history WAHA...';
  }
  const result = await guarded(() => api(`/api/contacts/${id}/sync-waha-history`, {
    method: 'POST',
    body: JSON.stringify({ limit: 300 }),
  }), 'History WAHA tersinkron');
  if (box) box.textContent = pretty(result.result);
  toast(`History: ${result.result.inserted} baru, ${result.result.skipped} dilewati`);
  await openContact(id);
  showContactTab('waha');
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
      memory_auto_generate_enabled: $('#detail-auto-memory').value,
      memory_generate_interval: $('#detail-interval').value,
    }),
  }), 'Pengaturan kontak tersimpan');
  await openContact(id);
  await loadContacts();
}

async function memoryAction(id, action) {
  if (action === 'reset' && !confirm('Reset memory kontak ini?')) return;
  const data = await guarded(() => api(`/api/contacts/${id}/memory/${action}`, { method: 'POST', body: '{}' }), action === 'reset' ? 'Memory direset' : 'Job memory dibuat');
  if (data.job_id) {
    showContactTab('memory');
    pollMemoryJob(data.job_id, id);
  } else {
    await openContact(id);
    await loadContacts();
  }
}

async function pollMemoryJob(jobId, contactId) {
  const box = $('#memory-job-status');
  if (!box) return;
  box.classList.remove('hidden');
  if (state.activeJobTimer) clearInterval(state.activeJobTimer);
  const render = (job) => {
    const pct = job.total ? Math.round((job.progress / job.total) * 100) : 0;
    box.innerHTML = `
      <strong>${esc(job.stage)} (${esc(job.status)})</strong>
      <div class="progress"><span style="width:${Math.max(3, pct)}%"></span></div>
      <small>${job.progress || 0}/${job.total || 0} batch</small>
      ${job.error ? `<pre class="code-box small">${esc(job.error)}</pre>` : ''}`;
  };
  const tick = async () => {
    const data = await api(`/api/memory-jobs/${jobId}`);
    render(data.job);
    if (['success', 'failed'].includes(data.job.status)) {
      clearInterval(state.activeJobTimer);
      state.activeJobTimer = null;
      if (data.job.status === 'success') {
        toast('Generate memory selesai');
        await openContact(contactId);
        showContactTab('memory');
      } else {
        toast('Generate memory gagal', 'error');
      }
    }
  };
  await guarded(tick);
  state.activeJobTimer = setInterval(() => guarded(tick), 2000);
}

async function saveMemory(id) {
  let memory_json;
  try {
    memory_json = JSON.parse($('#memory-json').value);
  } catch {
    toast('Memory JSON tidak valid', 'error');
    return;
  }
  await guarded(() => api(`/api/contacts/${id}/memory/save`, { method: 'POST', body: JSON.stringify({ memory_json }) }), 'Memory tersimpan');
  await openContact(id);
}

async function sendManual(wa_number) {
  const message = $('#manual-message').value.trim();
  if (!message) return toast('Pesan masih kosong', 'error');
  await guarded(() => api('/api/send-message', { method: 'POST', body: JSON.stringify({ wa_number, message }) }), 'Pesan terkirim');
  $('#manual-message').value = '';
  await openContact(state.activeContact);
}

function fieldHtml(key, label) {
  const val = state.config[key] || '';
  if (key.includes('list_numbers')) return `<label>${label}<textarea name="${key}" placeholder="Satu nomor per baris">${esc(val)}</textarea></label>`;
  if (['waha_enabled', 'global_auto_reply', 'default_contact_auto_reply', 'memory_auto_generate', 'allowlist_mode'].includes(key)) {
    return `<label>${label}<select name="${key}"><option value="true" ${val === 'true' ? 'selected' : ''}>On</option><option value="false" ${val !== 'true' ? 'selected' : ''}>Off</option></select></label>`;
  }
  if (key === 'memory_generate_mode') {
    return `<label>${label}<select name="${key}"><option value="manual_only" ${val === 'manual_only' ? 'selected' : ''}>Manual only</option><option value="auto_incremental" ${val === 'auto_incremental' ? 'selected' : ''}>Auto incremental</option><option value="manual_auto" ${val === 'manual_auto' ? 'selected' : ''}>Manual + auto incremental</option></select></label>`;
  }
  return `<label>${label}<input name="${key}" value="${esc(val)}"></label>`;
}

function settingsGroup(title, fields) {
  return `<fieldset><legend>${esc(title)}</legend>${fields.map(([key, label]) => fieldHtml(key, label)).join('')}</fieldset>`;
}

function renderSettings() {
  $('#settings-form').innerHTML = [
    settingsGroup('WAHA', [
      ['waha_base_url', 'WAHA Base URL'], ['waha_session', 'WAHA Session'], ['waha_api_key', 'WAHA API Key'], ['waha_enabled', 'Enable WAHA'],
      ['waha_sync_page_size', 'WAHA sync page size'], ['waha_sync_max_contacts', 'WAHA max contacts sync'], ['waha_history_sync_limit', 'WAHA history limit per contact'],
    ]),
    settingsGroup('Ollama', [
      ['ollama_base_url', 'Ollama Base URL'], ['chatbot_model', 'Model chatbot'], ['extractor_model', 'Model extractor'], ['merger_model', 'Model merger'],
      ['chatbot_temperature', 'Temperature chatbot'], ['extractor_temperature', 'Temperature extractor'], ['merger_temperature', 'Temperature merger'],
    ]),
    settingsGroup('Auto Reply', [
      ['global_auto_reply', 'Global auto reply'], ['reply_delay_seconds', 'Reply delay detik'], ['default_contact_auto_reply', 'Default kontak auto reply'],
      ['allowlist_mode', 'Allowlist mode'], ['blocklist_numbers', 'Blocklist nomor'], ['allowlist_numbers', 'Allowlist nomor'],
    ]),
    settingsGroup('Memory', [
      ['memory_auto_generate', 'Memory auto generate global'], ['memory_generate_interval', 'Default memory interval'], ['memory_generate_mode', 'Mode generate'], ['memory_batch_size', 'Memory batch size'],
    ]),
  ].join('');
}

function renderPrompts() {
  const fields = [
    ['prompt_chatbot_without_memory', 'Runtime prompt chatbot tanpa memory'],
    ['prompt_chatbot_with_memory', 'Runtime prompt chatbot dengan memory'],
    ['prompt_memory_extractor', 'Runtime prompt memory extractor'],
    ['prompt_memory_merger', 'Runtime prompt memory merger'],
  ];
  $('#prompts-form').innerHTML = fields.map(([key, label]) => `<label>${label}<textarea name="${key}">${esc(state.config[key] || '')}</textarea></label>`).join('');
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
  const logs = data.logs;
  $('#logs-table').innerHTML = `<thead><tr><th>Waktu</th><th>Level</th><th>Pesan</th><th>Context</th></tr></thead><tbody>${
    logs.length ? logs.map(l => `<tr><td>${esc(l.created_at_local || l.created_at)}</td><td><span class="log-level ${esc(l.level.toLowerCase())}">${esc(l.level)}</span></td><td>${esc(l.message)}</td><td><pre>${esc(l.context_json || '')}</pre></td></tr>`).join('') : '<tr><td class="empty-state" colspan="4">Tidak ada log yang cocok.</td></tr>'
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
on('#contact-search', 'input', () => {
  state.contactOffset = 0;
  guarded(loadContacts);
});
on('#add-contact', 'click', addContact);
on('#sync-waha-contacts', 'click', syncWahaContacts);
on('#save-settings', 'click', () => saveForm('#settings-form', '#settings-result'));
on('#save-prompts', 'click', () => saveForm('#prompts-form', '#prompts-result'));
on('#test-waha', 'click', () => testService('waha', '#settings-result'));
on('#test-ollama', 'click', () => testService('ollama', '#settings-result'));
on('#overview-test-waha', 'click', () => testService('waha', '#overview-test-result'));
on('#overview-test-ollama', 'click', () => testService('ollama', '#overview-test-result'));
on('#diag-test-waha', 'click', () => testService('waha', '#diag-service-result'));
on('#diag-test-ollama', 'click', () => testService('ollama', '#diag-service-result'));
on('#diag-update-status', 'click', () => guarded(loadDiagnostics, 'Status Git diperbarui'));
on('#refresh-logs', 'click', () => guarded(loadLogs));
on('#log-level', 'change', () => guarded(loadLogs));
on('#log-filter', 'input', () => {
  clearTimeout(logTimer);
  logTimer = setTimeout(() => guarded(loadLogs), 250);
});

loadConfig().then(refreshCurrent).catch(err => toast(err.message, 'error'));
