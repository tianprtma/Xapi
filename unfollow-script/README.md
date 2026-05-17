# Auto Unfollow Not Followback

Script Node.js buat auto-unfollow akun X (Twitter) yang gak follow back. Pake server **Xapi** lokal sebagai backend.

## Prasyarat

1. Server Xapi udah jalan di `http://127.0.0.1:8000` (lihat README utama).
2. Punya `auth_token` cookie dari `x.com`.
3. Node.js >= 18 (pake `fetch` bawaan).

## Setup

```bash
cd unfollow-script
npm install
cp .env.example .env
# edit .env, isi AUTH_TOKEN
```

## Pemakaian

```bash
# 1. Lihat siapa aja yang gak followback (gak unfollow apa-apa)
npm run list

# 2. Dry run (preview 20 target pertama, gak unfollow beneran)
npm run dry

# 3. Eksekusi unfollow
npm start
```

## Flag CLI

- `--list-only` — cuma fetch + simpan snapshot ke `out/`, skip unfollow
- `--dry-run` — preview target tanpa eksekusi

## Konfigurasi (.env)

| Var | Default | Fungsi |
|---|---|---|
| `XAPI_BASE_URL` | `http://127.0.0.1:8000` | Base URL server Xapi |
| `AUTH_TOKEN` | — | Cookie `auth_token` X.com |
| `UNFOLLOW_DELAY_MS` | `8000` | Jeda antar unfollow (ms) |
| `PAUSE_EVERY` | `25` | Pause panjang tiap N unfollow |
| `PAUSE_DURATION_MS` | `60000` | Durasi pause panjang (ms) |
| `MAX_UNFOLLOW` | `0` | Limit per run (0 = no limit) |
| `WHITELIST_IDS` | — | Comma-separated user ID yang gak akan di-unfollow |
| `WHITELIST_USERNAMES` | — | Comma-separated username (tanpa @) |

## Output

- `out/not-followback-*.json` — snapshot daftar target tiap run
- `logs/run-*.jsonl` — log per-aksi (sukses/fail) format JSONL

## Tips Anti-Banned

- Mulai pelan: `MAX_UNFOLLOW=20` dulu, lihat reaksi akun
- Naikkin `UNFOLLOW_DELAY_MS` ke 10000-15000 buat akun baru
- Kalau hit 429 berkali-kali, stop dulu beberapa jam
- Whitelist akun penting (mutual yang baru follow, akun bisnis, dll)

## Endpoint yang Dipake

- `GET /2/users/me` — ambil ID auth user
- `GET /2/users/{id}/following` — paginate daftar following
- `GET /2/users/{id}/followers` — paginate daftar followers (Playwright fallback kalau CF block)
- `DELETE /2/users/{me}/following/{target}` — eksekusi unfollow
