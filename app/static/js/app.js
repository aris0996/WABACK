const state = { config: {}, contacts: [], activeContact: null };

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const data = await res.json().catch(() => ({ ok: false, error: 'Invalid response' }));
  if (!res.ok || data.ok === false) throw new Error(data.error || 'Request failed');
  return data;
}

function show(view) {
  document.querySelectorAll('.nav').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
  if (view === 'overview') loadOverview();
  if (view === 'contacts') loadContacts();
  if (view === 'logs') loadLogs();
}

async function loadConfig() {
  const data = await api('/api/config');
  state.config = data.config;
  renderSettings();
  renderPrompts();
}

async function loadOverview() {
  const data = await api('/api/overview');
  const cards = [
    ['Kontak', data.stats.contacts],
    ['Pesan', data.stats.messages],
    ['Memory', data.stats.memories],
    ['Global Auto Reply', data.config.global_auto_reply],
    ['Memory Auto Generate', data.config.memory_auto_generate],
    ['WAHA URL', data.config.waha_base_url],
    ['Ollama URL', data.config.ollama_base_url],
  ];
  $('#overview-cards').innerHTML = cards.map(([label, value]) => `<div class="stat">${esc(label)}<strong>${esc(value)}</strong></div>`).join('');
}

async function loadContacts() {
  const q = encodeURIComponent($('#contact-search').value || '');
  const data = await api(`/api/contacts?q=${q}`);
  state.contacts = data.contacts;
  $('#contacts-table').innerHTML = `
    <thead><tr><th>Nomor</th><th>Nama</th><th>Auto Reply</th><th>AI Blocked</th><th>Memory</th><th>Pesan Baru</th><th>Interval</th><th>Terakhir Chat</th><th>Aksi</th></tr></thead>
    <tbody>${data.contacts.map(c => `
      <tr>
        <td>${esc(c.wa_number)}</td><td>${esc(c.display_name || '-')}</td>
        <td>${c.auto_reply_enabled ? 'On' : 'Off'}</td><td>${c.ai_blocked ? 'Ya' : 'Tidak'}</td>
        <td>${c.has_memory ? 'Ada' : 'Belum'}</td><td>${c.new_message_count_since_memory}</td>
        <td>${c.memory_generate_interval}</td><td>${esc(c.last_chat_at || '-')}</td>
        <td><div class="mini-actions">
          <button onclick="openContact(${c.id})">Detail</button>
          <button class="secondary" onclick="postAndReload('/api/contacts/${c.id}/toggle-auto-reply')">Toggle</button>
          <button class="${c.ai_blocked ? 'secondary' : 'danger'}" onclick="postAndReload('/api/contacts/${c.id}/${c.ai_blocked ? 'unblock-ai' : 'block-ai'}')">${c.ai_blocked ? 'Unblock' : 'Block'}</button>
        </div></td>
      </tr>`).join('')}</tbody>`;
}

async function postAndReload(path) {
  await api(path, { method: 'POST', body: '{}' });
  await loadContacts();
  if (state.activeContact) await openContact(state.activeContact);
}

async function openContact(id) {
  state.activeContact = id;
  const data = await api(`/api/contacts/${id}`);
  const c = data.contact;
  const memory = data.memory ? JSON.parse(data.memory.memory_json) : {};
  $('#contact-detail').classList.remove('hidden');
  $('#contact-detail').innerHTML = `
    <h3>${esc(c.wa_number)} <span class="pill">${esc(c.display_name || 'tanpa nama')}</span></h3>
    <div class="detail-grid">
      <div>
        <label>Nama display<input id="detail-name" value="${esc(c.display_name || '')}"></label>
        <label>Auto generate memory
          <select id="detail-auto-memory"><option value="true" ${c.memory_auto_generate_enabled ? 'selected' : ''}>On</option><option value="false" ${!c.memory_auto_generate_enabled ? 'selected' : ''}>Off</option></select>
        </label>
        <label>Interval generate<input id="detail-interval" type="number" min="1" value="${c.memory_generate_interval}"></label>
        <p>Pesan baru: <strong>${c.new_message_count_since_memory}</strong></p>
        <p>Last memory message ID: <strong>${c.last_memory_message_id}</strong></p>
        <div class="actions">
          <button onclick="saveContactSettings(${id})">Simpan kontak</button>
          <button onclick="memoryAction(${id}, 'generate-all')">Generate semua</button>
          <button onclick="memoryAction(${id}, 'generate-new')">Generate baru</button>
          <button class="danger" onclick="memoryAction(${id}, 'reset')">Reset memory</button>
        </div>
        <label>Memory JSON<textarea id="memory-json" class="memory-editor">${esc(JSON.stringify(memory, null, 2))}</textarea></label>
        <button onclick="saveMemory(${id})">Simpan memory manual</button>
        <hr>
        <label>Kirim pesan manual<textarea id="manual-message"></textarea></label>
        <button onclick="sendManual('${esc(c.wa_number)}')">Kirim via WAHA</button>
      </div>
      <div><h4>Riwayat Chat</h4><div class="chat-box">
        ${data.messages.map(m => `<div class="msg ${m.direction}"><small>#${m.id} ${esc(m.direction)} - ${esc(m.created_at)}</small>${esc(m.message)}</div>`).join('')}
      </div></div>
    </div>`;
}

async function saveContactSettings(id) {
  await api(`/api/contacts/${id}/settings`, { method: 'POST', body: JSON.stringify({
    display_name: $('#detail-name').value,
    memory_auto_generate_enabled: $('#detail-auto-memory').value,
    memory_generate_interval: $('#detail-interval').value
  })});
  await openContact(id);
  await loadContacts();
}

async function memoryAction(id, action) {
  if (action === 'reset' && !confirm('Reset memory kontak ini?')) return;
  await api(`/api/contacts/${id}/memory/${action}`, { method: 'POST', body: '{}' });
  await openContact(id);
  await loadContacts();
}

async function saveMemory(id) {
  const memory_json = JSON.parse($('#memory-json').value);
  await api(`/api/contacts/${id}/memory/save`, { method: 'POST', body: JSON.stringify({ memory_json }) });
  await openContact(id);
}

async function sendManual(wa_number) {
  await api('/api/send-message', { method: 'POST', body: JSON.stringify({ wa_number, message: $('#manual-message').value }) });
  $('#manual-message').value = '';
  await openContact(state.activeContact);
}

function renderSettings() {
  const fields = [
    ['waha_base_url','WAHA Base URL'], ['waha_session','WAHA Session'], ['waha_api_key','WAHA API Key'],
    ['waha_enabled','Enable WAHA'], ['ollama_base_url','Ollama Base URL'], ['chatbot_model','Model chatbot'],
    ['extractor_model','Model extractor'], ['merger_model','Model merger'], ['chatbot_temperature','Temperature chatbot'],
    ['extractor_temperature','Temperature extractor'], ['merger_temperature','Temperature merger'], ['global_auto_reply','Global auto reply'],
    ['reply_delay_seconds','Reply delay detik'], ['default_contact_auto_reply','Default kontak auto reply'],
    ['memory_auto_generate','Memory auto generate global'], ['memory_generate_interval','Default memory interval'],
    ['memory_generate_mode','Mode generate'], ['allowlist_mode','Allowlist mode'], ['blocklist_numbers','Blocklist nomor'], ['allowlist_numbers','Allowlist nomor']
  ];
  $('#settings-form').innerHTML = fields.map(([key, label]) => {
    const val = state.config[key] || '';
    if (key.includes('list_numbers')) return `<label>${label}<textarea name="${key}">${esc(val)}</textarea></label>`;
    if (['waha_enabled','global_auto_reply','default_contact_auto_reply','memory_auto_generate','allowlist_mode'].includes(key)) {
      return `<label>${label}<select name="${key}"><option value="true" ${val === 'true' ? 'selected' : ''}>On</option><option value="false" ${val !== 'true' ? 'selected' : ''}>Off</option></select></label>`;
    }
    if (key === 'memory_generate_mode') {
      return `<label>${label}<select name="${key}"><option value="manual_only" ${val === 'manual_only' ? 'selected' : ''}>Manual only</option><option value="auto_incremental" ${val === 'auto_incremental' ? 'selected' : ''}>Auto incremental</option><option value="manual_auto" ${val === 'manual_auto' ? 'selected' : ''}>Manual + auto incremental</option></select></label>`;
    }
    return `<label>${label}<input name="${key}" value="${esc(val)}"></label>`;
  }).join('');
}

function renderPrompts() {
  const fields = [
    ['prompt_chatbot_without_memory','Runtime prompt chatbot tanpa memory'],
    ['prompt_chatbot_with_memory','Runtime prompt chatbot dengan memory'],
    ['prompt_memory_extractor','Runtime prompt memory extractor'],
    ['prompt_memory_merger','Runtime prompt memory merger'],
  ];
  $('#prompts-form').innerHTML = fields.map(([key, label]) => `<label>${label}<textarea name="${key}">${esc(state.config[key] || '')}</textarea></label>`).join('');
}

async function saveForm(formSel, resultSel) {
  const data = Object.fromEntries(new FormData($(formSel)).entries());
  const res = await api('/api/config', { method: 'POST', body: JSON.stringify(data) });
  state.config = res.config;
  $(resultSel).textContent = 'Tersimpan.';
}

async function loadLogs() {
  const data = await api('/api/logs');
  $('#logs-table').innerHTML = `<thead><tr><th>Waktu</th><th>Level</th><th>Pesan</th><th>Context</th></tr></thead><tbody>${data.logs.map(l => `<tr><td>${esc(l.created_at)}</td><td>${esc(l.level)}</td><td>${esc(l.message)}</td><td>${esc(l.context_json || '')}</td></tr>`).join('')}</tbody>`;
}

document.querySelectorAll('.nav').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.view)));
$('#contact-search').addEventListener('input', () => loadContacts());
$('#save-settings').addEventListener('click', () => saveForm('#settings-form', '#settings-result'));
$('#save-prompts').addEventListener('click', () => saveForm('#prompts-form', '#prompts-result'));
$('#test-waha').addEventListener('click', async () => { $('#settings-result').textContent = JSON.stringify(await api('/api/test-waha', { method: 'POST', body: '{}' })); });
$('#test-ollama').addEventListener('click', async () => { $('#settings-result').textContent = JSON.stringify(await api('/api/test-ollama', { method: 'POST', body: '{}' })); });
$('#refresh-logs').addEventListener('click', loadLogs);

loadConfig().then(loadOverview).catch(err => alert(err.message));
