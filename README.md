# WhatsApp AI Automation Controller

Full-stack controller untuk menghubungkan Flutter Admin App, Flask Backend, WAHA WhatsApp API, Ollama, SQLite, APScheduler, dan WebSocket relay.

## Backend Install

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Backend default berjalan di `http://localhost:5000`. Database SQLite otomatis dibuat dan admin default otomatis disiapkan:

- Username: `admin`
- Password: `admin123`

## Docker

Dari folder `backend/`:

```bash
cp .env.docker.example .env
docker compose up -d --build
```

Backend akan tersedia lokal di `http://127.0.0.1:5050/api`. Untuk Linux server yang perlu akses Ollama host lewat `http://127.0.0.1:11434`, gunakan:

```bash
docker compose -f docker-compose.hostnet.yml up -d --build
```

Jika database lama masih menyimpan `ollama_base_url` yang salah, ubah dari Flutter Settings atau set `SYNC_ENV_SETTINGS_ON_BOOT=true` sekali saja.

## Environment

Edit `.env` jika perlu:

```env
SECRET_KEY=change-me
JWT_SECRET_KEY=change-me-too
DATABASE_URL=sqlite:///whatsapp_ai.db
HOST=0.0.0.0
PORT=5000
```

Settings WAHA, Ollama, dan relay disimpan di database lewat `GET/PUT /api/settings`.

## Flutter Install

```bash
cd flutter_app
flutter pub get
flutter run
```

Di login screen, gunakan backend URL `http://localhost:5000` untuk desktop/web lokal. Jika menjalankan di Android emulator, gunakan `http://10.0.2.2:5000`.

## WAHA Webhook

Set webhook WAHA menuju:

```text
http://<backend-host>:5000/api/webhook/waha
```

Semua request backend ke WAHA memakai header:

```text
X-Api-Key: <waha_api_key>
```

Catatan: endpoint typing WAHA berbeda antar instalasi. Service sudah mencoba endpoint umum dan fallback tanpa crash jika tidak tersedia.

## Relay WebSocket

Backend register sebagai `pc`:

```json
{
  "type": "register",
  "role": "pc",
  "device_id": "backend-waha-ai",
  "phone_id": "phone-aris",
  "token": "@arisdev09"
}
```

Flutter register sebagai `phone`:

```json
{
  "type": "register",
  "role": "phone",
  "device_id": "phone-aris",
  "token": "@arisdev09"
}
```

Event backend ke Flutter:

```json
{
  "type": "status",
  "target": "phone-aris",
  "token": "@arisdev09",
  "event": "inbox_new_message",
  "data": {}
}
```

Untuk produksi, ganti relay token menjadi token per device.

## Curl Test

Login:

```bash
curl -X POST http://localhost:5000/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"admin123\"}"
```

Simpan token, lalu:

```bash
curl http://localhost:5000/api/settings -H "Authorization: Bearer <JWT>"
```

Simulasi webhook pesan masuk:

```bash
curl -X POST http://localhost:5000/api/webhook/waha ^
  -H "Content-Type: application/json" ^
  -d "{\"session\":\"default\",\"chatId\":\"628123456789@c.us\",\"sender\":\"628123456789@c.us\",\"pushName\":\"User Test\",\"body\":\"Halo, apakah stok masih ada?\",\"id\":\"msg-1\",\"fromMe\":false,\"timestamp\":1718000000}"
```

Generate AI draft:

```bash
curl -X POST http://localhost:5000/api/messages/1/generate-ai ^
  -H "Authorization: Bearer <JWT>"
```

Kirim balasan:

```bash
curl -X POST http://localhost:5000/api/messages/1/send ^
  -H "Authorization: Bearer <JWT>" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Halo, stok masih tersedia.\"}"
```

Scheduled message:

```bash
curl -X POST http://localhost:5000/api/scheduled ^
  -H "Authorization: Bearer <JWT>" ^
  -H "Content-Type: application/json" ^
  -d "{\"target_chat_id\":\"628123456789@c.us\",\"message\":\"Reminder ya\",\"schedule_time\":\"2026-06-14T10:30:00\",\"repeat\":\"none\",\"enabled\":true}"
```

## Alur Test

1. Jalankan Flask backend.
2. Jalankan Flutter dan login.
3. Buka Settings, cek WAHA, Ollama, dan relay.
4. Set webhook WAHA ke `/api/webhook/waha`.
5. Kirim pesan WhatsApp masuk atau pakai curl simulasi.
6. Buka Inbox, pesan harus muncul.
7. Buka detail pesan, klik Generate AI.
8. Edit draft jika perlu lalu kirim balasan.
9. Buat scheduled message dan tunggu scheduler mengirim.
10. Buka Logs untuk melihat aktivitas masuk, keluar, error WAHA, dan scheduled.

## Endpoint Ringkas

- `POST /api/auth/login`
- `GET/PUT /api/settings`
- `GET/POST /api/contacts`
- `GET/PUT/DELETE /api/contacts/<id>`
- `GET /api/messages`
- `GET /api/messages/<id>`
- `GET /api/messages/chat/<chat_id>`
- `POST /api/messages/<id>/generate-ai`
- `POST /api/messages/<id>/send`
- `POST /api/messages/<id>/ignore`
- `POST /api/messages/<id>/block-contact`
- `GET/POST /api/scheduled`
- `GET/PUT/DELETE /api/scheduled/<id>`
- `GET /api/logs`
- `POST /api/webhook/waha`

## Auto Reply

Auto reply hanya berjalan jika:

- pesan bukan `fromMe`
- contact tidak `blocked`
- `reply_mode` bukan `disabled` atau `manual_only`
- grup memiliki `trigger_keyword`
- masih dalam jam aktif jika `active_start` dan `active_end` diisi
- untuk kirim otomatis, contact harus `permission=allowed` dan `reply_mode=auto_reply`

Mode `ai_draft` hanya membuat draft dan tidak mengirim ke WhatsApp.
