# WhatsApp AI Auto Reply dengan Memory

Aplikasi Flask untuk menerima webhook WAHA, menyimpan chat WhatsApp, membalas otomatis lewat Ollama, dan membuat memory per kontak secara manual atau otomatis incremental.

## Install

```bash
cp .env.example .env
docker compose up -d --build
```

Buka dashboard di `http://localhost:5000`, lalu login memakai `ADMIN_USERNAME` dan `ADMIN_PASSWORD` dari `.env`.

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
