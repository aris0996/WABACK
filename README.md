# WhatsApp AI Auto Reply dengan Memory

Aplikasi Flask untuk menerima webhook WAHA, menyimpan chat WhatsApp, membalas otomatis lewat Ollama, dan membuat memory per kontak secara manual atau otomatis incremental.

## Install

```bash
cp .env.example .env
docker compose up -d --build
```

Buka dashboard di `http://localhost:5000`, lalu login memakai `ADMIN_USERNAME` dan `ADMIN_PASSWORD` dari `.env`.

## Build dengan Log Detail

Untuk melihat proses build lebih lengkap, gunakan script build yang menampilkan tahapan, persentase fase, log Docker detail, status container, dan log awal aplikasi.

Windows PowerShell:

```powershell
.\build.ps1
```

Linux/macOS:

```bash
chmod +x build.sh
./build.sh
```

Build ulang tanpa cache:

```powershell
.\build.ps1 -NoCache
```

```bash
./build.sh --no-cache
```

Hanya build tanpa menjalankan container:

```powershell
.\build.ps1 -SkipStart
```

```bash
./build.sh --skip-start
```

Catatan: Docker tidak menyediakan persentase real untuk setiap layer build. Persentase di script menunjukkan fase proses, sementara detail layer tetap berasal dari `docker compose build --progress=plain`.

## Konfigurasi `.env`

Minimal ubah:

```env
SECRET_KEY=isi-random-panjang
ADMIN_USERNAME=admin
ADMIN_PASSWORD=password-kuat
WEBHOOK_TOKEN=token-webhook-kuat
```

SQLite default tersimpan di `./data/app.db`. Struktur akses database dipusatkan di `app/db.py` supaya lebih mudah diganti ke MySQL/PostgreSQL nanti.

## Ollama

Buat model dari Modelfile. Personality utama chatbot wajib berada di model, bukan hanya prompt runtime dashboard.

```bash
ollama create wa-chatbot -f ollama-models/wa-chatbot.Modelfile
ollama create wa-memory-extractor -f ollama-models/wa-memory-extractor.Modelfile
ollama create wa-memory-merger -f ollama-models/wa-memory-merger.Modelfile
```

Default base model:

```text
FROM qwen2.5:3b
```

Jika ingin model lain, ubah baris `FROM` di setiap file `ollama-models/*.Modelfile`, lalu jalankan ulang `ollama create`.

Di dashboard, buka Settings dan isi `Ollama Base URL`, model chatbot, extractor, dan merger. Dari container Docker, biasanya host Ollama memakai `http://host.docker.internal:11434`.

## WAHA

Jalankan WAHA secara terpisah atau di container lain, lalu isi di Settings:

- WAHA Base URL
- WAHA Session
- WAHA API Key jika dipakai
- Enable WAHA integration

Set webhook WAHA ke:

```text
POST http://localhost:5000/webhook/waha
Header: X-Webhook-Token: token-webhook-kuat
```

Jika Flask berjalan di Docker dan WAHA berada di container lain, gunakan hostname/network yang bisa saling diakses.

## GitHub Auto Update

Aplikasi menyediakan endpoint update:

```text
POST /webhook/github
GET  /webhook/github/status
```

Konfigurasi di `.env`:

```env
GITHUB_WEBHOOK_SECRET=secret-yang-sama-dengan-github
AUTO_UPDATE_API_KEY=opsional-api-key
AUTO_UPDATE_BRANCH=main
AUTO_UPDATE_COMMAND=
AUTO_UPDATE_TIMEOUT=300
```

Di GitHub repository, buka Settings, Webhooks, Add webhook:

- Payload URL: `http://IP_SERVER:PORT/webhook/github`
- Content type: `application/json`
- Secret: isi sama dengan `GITHUB_WEBHOOK_SECRET`
- Event: `Just the push event`

Jika `AUTO_UPDATE_API_KEY` diisi, request juga harus membawa header:

```text
X-Update-Key: isi-api-key
```

GitHub webhook standar tidak mudah menambah header custom. Karena itu, untuk GitHub murni cukup pakai `GITHUB_WEBHOOK_SECRET`. `AUTO_UPDATE_API_KEY` berguna jika update dipanggil dari tool lain seperti curl, reverse proxy, atau automation pribadi.

Update dibuat aman untuk mencegah konflik:

```bash
git fetch --prune origin
git pull --ff-only origin main
```

Sistem akan menolak update jika working tree tidak bersih. Ini mencegah konflik file/folder dan mencegah server membuat merge commit otomatis. File runtime seperti `.env`, `data/`, database SQLite, cache Python, dan log sudah dimasukkan ke `.gitignore`.

Jika `.env` sudah pernah terlanjur masuk Git, jalankan sekali:

```bash
git rm --cached .env
git commit -m "Stop tracking local env file"
```

Cek status update manual:

```bash
curl -H "X-Update-Key: isi-api-key" http://IP_SERVER:PORT/webhook/github/status
```

Endpoint status hanya aktif jika `AUTO_UPDATE_API_KEY` diisi.

Jika deploy berjalan langsung di host, `AUTO_UPDATE_COMMAND` bisa diisi:

```env
AUTO_UPDATE_COMMAND=docker compose up -d --build
```

Catatan Docker: endpoint auto update membutuhkan folder kerja yang memiliki `.git` dan binary `git`. Jika aplikasi berjalan di container hasil `COPY . .`, `.git` biasanya tidak ikut masuk image. Untuk auto update paling sederhana, jalankan aplikasi di host repository, atau panggil endpoint update dari service host yang punya akses ke Git dan Docker.

## Memory Manual

Buka Contacts, pilih Detail kontak, lalu gunakan:

- Generate semua: membaca seluruh history kontak.
- Generate baru: hanya membaca pesan dengan `id > last_memory_message_id`.
- Reset memory: hapus memory final dan candidate, set checkpoint ke `0`.
- Simpan memory manual: edit JSON final langsung dari dashboard.

Format memory final:

```json
{
  "nama": "none",
  "panggilan": "none",
  "pekerjaan": "none",
  "sekolah": "none",
  "lokasi": "none",
  "minat": [],
  "kebutuhan": [],
  "gaya_bahasa": "none",
  "catatan_penting": [],
  "larangan": [],
  "hubungan_dengan_saya": "none",
  "last_summary": "none"
}
```

## Auto Generate Memory Incremental

Setiap pesan masuk disimpan ke tabel `messages`, lalu `contacts.new_message_count_since_memory` bertambah. Jika mencapai interval default `20`, sistem hanya mengambil pesan baru:

```sql
SELECT * FROM messages
WHERE contact_id = ? AND id > contacts.last_memory_message_id
ORDER BY id ASC
```

Setelah extractor dan merger berhasil, sistem update:

- `contacts.last_memory_message_id = id pesan terakhir yang diproses`
- `contacts.new_message_count_since_memory = 0`
- `messages.used_for_memory = true`

Jika generate gagal, checkpoint tidak diubah.

## Auto Reply

Urutan pengecekan webhook:

1. Validasi `X-Webhook-Token`.
2. Simpan pesan mentah.
3. Cek global auto reply.
4. Cek blocklist dan allowlist.
5. Cek setting kontak dan status AI blocked.
6. Generate balasan dengan memory jika ada.
7. Kirim via WAHA dan simpan pesan keluar.
8. Cek auto memory incremental.

## Troubleshooting

### Ollama tidak konek

- Pastikan Ollama berjalan: `ollama list`.
- Dari Docker, gunakan `http://host.docker.internal:11434`.
- Pastikan model sudah dibuat dengan `ollama create`.

### WAHA tidak konek

- Cek WAHA Base URL dan API key.
- Klik Test WAHA di dashboard.
- Pastikan session WAHA aktif.

### AI tidak membalas

- Cek Global auto reply.
- Cek kontak tidak diblokir AI.
- Cek allowlist/blocklist.
- Cek WAHA enabled dan koneksi WAHA.
- Lihat Logs untuk error Ollama atau WAHA.

### Memory tidak tergenerate

- Pastikan Memory auto generate global aktif.
- Pastikan auto generate kontak aktif.
- Cek interval dan jumlah pesan baru.
- Coba Generate baru dari detail kontak.
- Lihat Logs untuk error JSON dari model extractor/merger.

### Docker tidak bisa akses Ollama host

- Gunakan `DEFAULT_OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- Di Linux tertentu, tambahkan host gateway di compose jika diperlukan.
