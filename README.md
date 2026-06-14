# WhatsApp AI Automation Controller Backend

Backend ini adalah pusat kendali untuk:

- menerima webhook dari WAHA
- menyimpan inbox ke SQLite
- membuat draft AI dengan Ollama
- mengirim balasan lewat WAHA
- menjalankan auto reply berbasis rule per kontak
- mengirim update realtime ke Flutter lewat relay WebSocket
- menjalankan scheduled message

Flutter admin app berada di folder terpisah: [whatsapp_ai](/D:/Whatsapp%20ai/whatsapp_ai).

## 1. Arsitektur Singkat

Alur utamanya seperti ini:

1. Pesan WhatsApp masuk ke WAHA
2. WAHA memanggil webhook backend `/api/webhook/waha`
3. Backend menyimpan pesan ke database
4. Backend mengecek rule kontak:
   - blocked
   - manual only
   - AI draft
   - auto reply
5. Jika perlu AI, backend memanggil Ollama
6. Jika perlu kirim balasan, backend memanggil WAHA
7. Backend mengirim event realtime ke Flutter melalui relay server

## 2. Struktur Folder

```text
backend/
  app/
    routes/       # endpoint API
    services/     # WAHA, Ollama, AI, relay, scheduler
    middleware/   # auth JWT
    models.py     # tabel database
    seed.py       # default admin + setting awal + schema patch ringan
  deploy/
    apache-streamdeck-whatsapp-ai.conf
  docker-compose.yml
  docker-compose.hostnet.yml
  requirements.txt
  run.py
```

## 3. Fitur yang Sudah Ada

- Login admin dengan JWT
- Settings WAHA, Ollama, relay
- Sync daftar chat WA dari WAHA
- Rules per kontak/chat
- Inbox pesan
- Chat viewer tanpa mark as read
- Generate AI draft
- Kirim balasan manual
- Auto reply berbasis permission + mode + jam aktif + keyword + cooldown + limit harian
- Scheduled message
- Logs detail
- Event realtime ke Flutter lewat relay

## 4. Requirement

Pastikan server/lokal Anda punya:

- Python 3.10+
- pip
- WAHA yang aktif
- Ollama yang aktif
- akses ke SQLite file lokal
- relay server WebSocket jika ingin realtime Flutter

## 5. Install Lokal Tanpa Docker

```powershell
cd D:\Whatsapp ai\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Default backend:

- URL: `http://127.0.0.1:5000`
- health check: `http://127.0.0.1:5000/api/health`

Saat start pertama:

- database SQLite otomatis dibuat
- tabel otomatis dibuat
- patch schema ringan otomatis dijalankan
- admin default otomatis dibuat

Admin default:

- username: `admin`
- password: `admin123`

## 6. Install Dengan Docker

### Opsi A: Docker bridge biasa

Gunakan ini kalau backend container mengakses Ollama host lewat `host.docker.internal`.

```powershell
cd D:\Whatsapp ai\backend
copy .env.docker.example .env
docker compose up -d --build
```

Default hasilnya:

- backend publish di `http://127.0.0.1:5050`

### Opsi B: Docker host network

Gunakan ini kalau:

- server Linux
- Ollama hanya listen di `127.0.0.1:11434`
- Anda ingin backend container tetap mengakses `http://127.0.0.1:11434`

```bash
cd /path/to/backend
cp .env.docker.example .env
docker compose -f docker-compose.hostnet.yml up -d --build
```

## 7. Konfigurasi `.env`

Contoh minimal:

```env
SECRET_KEY=change-me
JWT_SECRET_KEY=change-me-too
DATABASE_URL=sqlite:///whatsapp_ai.db
HOST=0.0.0.0
PORT=5000

WAHA_BASE_URL=http://127.0.0.1:3000
WAHA_API_KEY=arisdev09
WAHA_SESSION=default

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1
OLLAMA_TEMPERATURE=0.7
OLLAMA_MAX_CHARS=800

RELAY_SERVER_URL=ws://streamdeck.arisdev.my.id/ws
RELAY_TOKEN=@arisdev09
RELAY_BACKEND_DEVICE_ID=backend-waha-ai
RELAY_BACKEND_ROLE=pc
RELAY_FLUTTER_TARGET_DEVICE_ID=phone-aris

SYNC_ENV_SETTINGS_ON_BOOT=false
```

Catatan penting:

- setelah settings pernah disimpan dari aplikasi, nilai aktif utama ada di database
- `.env` tidak otomatis menimpa database kecuali `SYNC_ENV_SETTINGS_ON_BOOT=true`
- jika Anda mau “paksa reset” setting dari `.env` sekali, aktifkan `SYNC_ENV_SETTINGS_ON_BOOT=true`, restart backend, lalu kembalikan ke `false`

## 8. Konfigurasi Server yang Direkomendasikan

Untuk kasus Anda:

- WAHA lokal server: `http://127.0.0.1:3000`
- Ollama lokal server: `http://127.0.0.1:11434`
- backend Docker lokal: `http://127.0.0.1:5050`
- domain publik via Apache/Virtualmin: `https://streamdeck.arisdev.my.id/api`

## 9. Proxy Apache / Virtualmin

Gunakan snippet di:

[apache-streamdeck-whatsapp-ai.conf](/D:/Whatsapp%20ai/backend/deploy/apache-streamdeck-whatsapp-ai.conf)

Inti konfigurasinya:

```apache
ProxyPass /.well-known !

ProxyPass /api http://127.0.0.1:5050/api
ProxyPassReverse /api http://127.0.0.1:5050/api

ProxyPass /ws ws://127.0.0.1:8765/
ProxyPassReverse /ws ws://127.0.0.1:8765/
```

Setelah edit Apache:

```bash
apachectl configtest
systemctl reload apache2
```

## 10. URL Penting

Jika backend berjalan di server Anda:

- API publik: `https://streamdeck.arisdev.my.id/api`
- webhook WAHA: `https://streamdeck.arisdev.my.id/api/webhook/waha`
- relay WebSocket: `ws://streamdeck.arisdev.my.id/ws` atau `wss://...` jika TLS aktif

## 11. Login API

Request:

```bash
curl -X POST http://127.0.0.1:5000/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"admin123\"}"
```

Contoh response:

```json
{
  "access_token": "JWT_TOKEN",
  "user": {
    "id": 1,
    "username": "admin"
  }
}
```

Gunakan token ini di header:

```text
Authorization: Bearer <JWT_TOKEN>
```

## 12. Cara Setting dari Awal

Urutan yang aman:

1. login ke Flutter atau pakai curl
2. buka menu Settings
3. isi WAHA:
   - `waha_base_url = http://127.0.0.1:3000`
   - `waha_api_key = arisdev09`
   - `waha_session = default`
4. isi Ollama:
   - `ollama_base_url = http://127.0.0.1:11434`
   - pilih model dari dropdown
5. isi relay:
   - `relay_server_url = ws://streamdeck.arisdev.my.id/ws`
   - `relay_token = @arisdev09`
   - `relay_backend_device_id = backend-waha-ai`
   - `relay_backend_role = pc`
   - `relay_flutter_target_device_id = phone-aris`
6. save settings
7. test WAHA
8. test Ollama

## 13. Test WAHA dan Ollama

### Test WAHA

```bash
curl http://127.0.0.1:5000/api/settings/test-waha ^
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### Test Ollama

```bash
curl http://127.0.0.1:5000/api/settings/test-ollama ^
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### Ambil daftar model Ollama

```bash
curl http://127.0.0.1:5000/api/settings/ollama-models ^
  -H "Authorization: Bearer <JWT_TOKEN>"
```

## 14. Konfigurasi Webhook WAHA

Atur WAHA agar memanggil:

```text
https://streamdeck.arisdev.my.id/api/webhook/waha
```

Minimal data yang backend parsing:

- session
- chatId
- sender
- body / text
- id
- fromMe
- timestamp
- isGroup

Simulasi manual:

```bash
curl -X POST http://127.0.0.1:5000/api/webhook/waha ^
  -H "Content-Type: application/json" ^
  -d "{\"session\":\"default\",\"chatId\":\"628123456789@c.us\",\"sender\":\"628123456789@c.us\",\"pushName\":\"User Test\",\"body\":\"Halo admin\",\"id\":\"msg-1\",\"fromMe\":false,\"timestamp\":1718000000}"
```

## 15. Cara Menggunakan Kontak & Rules

### Default perilaku chat baru

Saat chat baru tersinkron dari WAHA:

- `permission = blocked`
- `reply_mode = disabled`

Artinya aman: AI tidak langsung membalas siapa pun.

### Preset cepat

Di menu `Kontak & Rules` ada preset:

- `Off` -> `blocked + disabled`
- `Manual` -> `allowed + manual_only`
- `Draft AI` -> `allowed + ai_draft`
- `Auto Reply` -> `allowed + auto_reply`

### Pengaturan advanced per kontak

Setiap kontak bisa punya:

- `type`: `private` / `group`
- `trigger_keyword`
- `keyword_match_mode`: `contains` / `exact` / `regex`
- `active_start`, `active_end`
- `priority_level`: `low`, `normal`, `high`, `vip`
- `daily_auto_reply_limit`
- `cooldown_seconds`
- `fallback_to_draft_on_error`
- `ai_style_override`
- `max_chars_override`
- `notes`

### Aturan yang disarankan

#### Private chat

Untuk private chat normal:

- `allowed + auto_reply` bila ingin AI balas otomatis
- keyword biasanya tidak wajib

#### Group chat

Untuk group:

- sangat disarankan tetap `manual_only` atau `blocked`
- jika auto reply aktif, sebaiknya isi `trigger_keyword`

## 16. Cara Sync Chat WA

Endpoint:

- `GET /api/contacts/waha`
- `POST /api/contacts/sync-waha`

Tujuan sync:

- ambil daftar chat terbaru dari WAHA
- buat/memperbarui kontak di database
- tetap mempertahankan rule yang sudah Anda edit manual

## 17. Cara Melihat Inbox

Flow:

1. pesan masuk ke WAHA
2. WAHA kirim webhook ke backend
3. backend simpan ke `messages`
4. Flutter menampilkan di `Inbox`

Endpoint penting:

- `GET /api/messages`
- `GET /api/messages/<id>`
- `GET /api/messages/chat/<chat_id>`
- `GET /api/messages/waha-chat/<chat_id>`

Catatan:

- `waha-chat` dipakai untuk baca chat langsung dari WAHA
- screen WA Chats dibuat agar bisa lihat chat tanpa menandai terbaca

## 18. Cara Generate Draft AI dan Kirim Balasan

### Generate draft AI

```bash
curl -X POST http://127.0.0.1:5000/api/messages/1/generate-ai ^
  -H "Authorization: Bearer <JWT_TOKEN>"
```

Backend akan:

1. ambil pesan terbaru
2. ambil 10 riwayat chat terakhir
3. gabungkan dengan setting global + override kontak
4. panggil Ollama
5. simpan ke tabel `ai_drafts`

### Kirim balasan

```bash
curl -X POST http://127.0.0.1:5000/api/messages/1/send ^
  -H "Authorization: Bearer <JWT_TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Halo, stok masih tersedia.\"}"
```

## 19. Cara Kerja Auto Reply

Auto reply hanya jalan jika semua syarat ini lolos:

- pesan bukan `from_me`
- body pesan tidak kosong
- kontak match ke rule yang benar
- `permission = allowed`
- `reply_mode = auto_reply`
- tidak di luar jam aktif
- tidak kena cooldown
- tidak kena limit harian
- jika group, keyword lolos
- Ollama bisa generate
- WAHA bisa kirim

### Status log yang sering muncul

- `received`
- `webhook_parsed`
- `auto_reply_check`
- `contact_resolved`
- `blocked`
- `disabled`
- `manual_only`
- `outside_active_hours`
- `keyword_not_matched`
- `cooldown_active`
- `daily_limit_reached`
- `draft_created`
- `auto_reply_start`
- `auto_reply_sent`
- `auto_reply_failed`
- `fallback_to_draft`
- `empty_ai_response`

Kalau auto reply tidak jalan, cek menu `Logs` dan lihat status terakhir.

## 20. Cara Membaca Penyebab AI Tidak Auto Reply

### Kasus 1: status `blocked`

Artinya kontak yang match ke pesan masih `blocked`.

### Kasus 2: status `disabled`

Artinya rule kontak masih `disabled`.

### Kasus 3: status `contact_resolved` tapi kontak salah

Biasanya ada mismatch `chat_id`, misalnya:

- `628xxxx@c.us`
- `628xxxx@lid`
- `628xxxx`

Solusinya:

- sync lagi dari WAHA
- cek kontak mana yang benar-benar kena webhook
- lihat `contact_resolved` di logs

### Kasus 4: status `fallback_to_draft`

AI generate atau WAHA kirim gagal, jadi sistem simpan draft dulu.

### Kasus 5: tidak ada log sama sekali

Biasanya webhook WAHA belum masuk ke backend.

## 21. Scheduled Message

Endpoint:

- `GET /api/scheduled`
- `POST /api/scheduled`
- `PUT /api/scheduled/<id>`
- `DELETE /api/scheduled/<id>`

### Contoh create scheduled

```bash
curl -X POST http://127.0.0.1:5000/api/scheduled ^
  -H "Authorization: Bearer <JWT_TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d "{\"target_chat_id\":\"628123456789@c.us\",\"message\":\"Reminder ya\",\"schedule_time\":\"2026-06-14T02:30:00Z\",\"repeat\":\"none\",\"enabled\":true}"
```

Catatan:

- backend menyimpan waktu dalam UTC
- Flutter mengirim UTC dan menampilkan ulang ke waktu lokal
- gunakan jadwal baru jika sebelumnya pernah tersimpan saat bug timezone masih ada

### Status scheduled

- `pending`
- `due`
- `scheduled_sent`
- `scheduled_error`

## 22. Relay WebSocket

### Register backend

```json
{
  "type": "register",
  "role": "pc",
  "device_id": "backend-waha-ai",
  "phone_id": "phone-aris",
  "token": "@arisdev09"
}
```

### Register Flutter

```json
{
  "type": "register",
  "role": "phone",
  "device_id": "phone-aris",
  "token": "@arisdev09"
}
```

### Format event backend ke Flutter

```json
{
  "type": "status",
  "target": "phone-aris",
  "token": "@arisdev09",
  "event": "inbox_new_message",
  "data": {}
}
```

### Event yang dipakai aplikasi

- `inbox_new_message`
- `ai_stream_chunk`
- `ai_draft_ready`
- `message_replied`
- `scheduled_message_sent`

### Catatan penting relay

Gunakan format URL yang valid:

- `ws://streamdeck.arisdev.my.id/ws`
- `wss://streamdeck.arisdev.my.id/ws`

Jangan gunakan:

- `http://.../ws`
- `http://...:0/ws`

## 23. Logs

Endpoint:

```bash
curl http://127.0.0.1:5000/api/logs ^
  -H "Authorization: Bearer <JWT_TOKEN>"
```

Filter:

- `chat_id`
- `direction`
- `status`
- `date_from`
- `date_to`

Logs adalah tempat utama untuk debug:

- apakah webhook masuk
- apakah contact match benar
- apakah AI generate
- apakah WAHA kirim
- apakah scheduled gagal

## 24. Endpoint Ringkas

- `POST /api/auth/login`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/settings/test-waha`
- `GET /api/settings/ollama-models`
- `GET /api/settings/test-ollama`
- `GET /api/contacts`
- `POST /api/contacts`
- `GET /api/contacts/summary`
- `GET /api/contacts/waha`
- `POST /api/contacts/sync-waha`
- `GET /api/contacts/rules-preview/<chat_id>`
- `POST /api/contacts/<id>/preset`
- `GET /api/contacts/<id>`
- `PUT /api/contacts/<id>`
- `DELETE /api/contacts/<id>`
- `GET /api/messages`
- `GET /api/messages/waha-chat/<chat_id>`
- `POST /api/messages/send-to-chat`
- `GET /api/messages/<id>`
- `GET /api/messages/chat/<chat_id>`
- `POST /api/messages/<id>/generate-ai`
- `POST /api/messages/<id>/send`
- `POST /api/messages/<id>/ignore`
- `POST /api/messages/<id>/block-contact`
- `GET /api/scheduled`
- `POST /api/scheduled`
- `GET /api/scheduled/<id>`
- `PUT /api/scheduled/<id>`
- `DELETE /api/scheduled/<id>`
- `GET /api/logs`
- `POST /api/webhook/waha`
- `GET /api/health`

## 25. Cara Pakai Harian yang Direkomendasikan

Urutan yang paling enak dipakai sehari-hari:

1. buka aplikasi Flutter
2. login
3. buka `Settings`
4. test WAHA
5. test Ollama
6. buka `WA Chats`
7. refresh dan sync kontak
8. buka `Kontak & Rules`
9. atur chat tertentu:
   - Off
   - Manual
   - Draft AI
   - Auto Reply
10. buka `Inbox`
11. lihat pesan baru
12. generate draft jika perlu
13. kirim manual atau biarkan auto reply bekerja
14. buka `Scheduled`
15. buat timer pesan
16. buka `Logs` jika ada masalah

## 26. Troubleshooting

### WAHA bisa di-curl tapi app tidak sync chat

Cek:

- `waha_base_url`
- `waha_api_key`
- `waha_session`
- apakah backend server memang bisa akses URL WAHA yang sama

Gunakan:

```bash
curl http://127.0.0.1:5000/api/settings/test-waha ^
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### Ollama tidak terbaca

- pastikan `ollama_base_url` benar
- test dari backend, bukan dari HP
- cek model list dari endpoint `/api/settings/ollama-models`

### Auto reply tidak jalan

Cek `Logs` dan cari status:

- `blocked`
- `disabled`
- `manual_only`
- `outside_active_hours`
- `keyword_not_matched`
- `cooldown_active`
- `daily_limit_reached`
- `fallback_to_draft`
- `auto_reply_failed`

### Scheduled message tidak terkirim

- pastikan backend hidup terus
- pastikan schedule baru dibuat setelah bug timezone diperbaiki
- cek status `scheduled_sent` atau `scheduled_error`

### Relay error berulang di Flutter

Periksa `relay_server_url`:

- harus `ws://...` atau `wss://...`
- jangan `http://`
- jangan port `0`

### Tidak ada log sama sekali

Kemungkinan:

- webhook WAHA belum masuk
- backend yang aktif bukan backend yang sama dengan yang dipakai Flutter
- request gagal sebelum sampai route

## 27. Catatan Keamanan

- jangan expose WAHA API key langsung ke Flutter
- gunakan token relay per device untuk produksi
- ganti password admin default
- ganti `SECRET_KEY` dan `JWT_SECRET_KEY`
- batasi akses server backend di firewall bila perlu

## 28. Quick Start Super Singkat

Kalau mau cepat hidup:

1. jalankan backend
2. login admin
3. isi settings WAHA + Ollama + relay
4. test WAHA
5. test Ollama
6. set webhook WAHA
7. sync kontak dari WA
8. set satu kontak ke `Auto Reply`
9. kirim pesan test
10. cek logs

