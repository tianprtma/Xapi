# Xapi Audit — Bug Fix Suite & XChat E2EE Live Test
Date: 2026-11-08
Scope: algoritma (formatter, pool/cache, DM pagination, XChat E2EE) + live test dengan akun nyata

## Metodologi

Setiap temuan diverifikasi dengan script repro yang dijalankan (bukan review baca-saja):
red (bug reproduksi) → fix → green (repro gagal-sesuai-harapan + regresi lolos).
Script verifikasi tersimpan di `/tmp/xapi_verify_scripts/` (sesi audit 2026-11-08).

## Bug ditemukan & difix (10)

| # | Bug | Lokasi | Bukti |
|---|---|---|---|
| 1 | Truncation menimpa `next_token` dengan id event → cursor upstream hilang, token bermacam tipe | `formatter.py` `format_dm_events`, `app/routers/dm.py` `_format_dm_events_smart` | repro pagination (duplikat boundary antar halaman) |
| 2 | `ClientPool` evict/TTL-sweep menutup session yang masih in-use (lock dipegang) | `app/client_pool.py` | repro curl_cffi: `SessionClosed` pada session ter-checkout |
| 3 | Null-unsafe `.get(k, {})` pada `null` eksplisit GraphQL → AttributeError → 500 | `formatter.py` (7 lokasi) | repro 5 kasus crash |
| 4 | Data loss `/2/dm_events`: merge multi-source > `max_results` dipotong, tapi token = cursor upstream yang melewati event terpotong | `formatter.py` + `dm.py` | repro: 20 event hilang permanen per halaman |
| 5 | `GetMessageRequestsPageQuery` di-refetch tiap halaman → event requests duplikat antar halaman | `app/routers/dm.py` `v2_dm_events` | repro cross-page duplikat |
| 6 | Sort `created_at` format campuran (`"…:00Z"` vs `"…:00.500Z"`) → urutan kronologis salah (lexicographic `'Z' > '.'`) | `formatter.py` `_dm_ts_to_iso` + sort | repro 3 event salah urut |
| 7 | `page.wait_for_function(expr, ARG, timeout=…)` positional arg — di playwright ≥1.4x `arg` keyword-only → TypeError → **seluruh jalur XChat E2EE mati** | `app/xchat_e2ee.py` (5 call site) | live test PIN: unlock crash |
| 8 | Race: XChat merender shell `dm-container` sesaat sebelum redirect ke gate PIN → "ready" prematur → PIN tak diketik → inbox kosong | `app/xchat_e2ee.py` `_ensure_pin_unlocked` | live test: screenshot gate sementara probe bilang ready |
| 9 | Shutdown menutup `PlaywrightPool` (driver) sebelum `XChatContextPool` → transport persistent context mati (`TargetClosedError`) → flush storage unlock E2EE terlewat | `main.py` lifespan | repro RPC mati setelah driver stop |
| 10 | `preview_text` kotor (nama+umur menempel; race render baris → preview = nama saja) | `app/xchat_e2ee.py` `unlock_and_read_xchat_inbox` | live: 5/8 preview kotor → 8/8 bersih |

## Fitur baru yang diverifikasi live

- **XChat E2EE via PIN** (`?dm_pin=` / `X-DM-Pin`): unlock + dekripsi oleh JS resmi X
  di headless Chromium; inbox 19 conv + percakapan terdekripsi + media.
- **Profil browser persist per akun** (`XChatContextPool`, `XCHAT_PROFILE_DIR`,
  `XCHAT_PERSISTENT_MAX`): PIN tidak diketik ulang tiap run; gate PIN dikontrol
  server X dan **flaky** — script/API menangani kedua kasus.
- **ct0 stabil per profil**: X mengikat sesi unlock E2EE ke identitas session (ct0);
  ct0 acak baru per run memicu gate ulang (disimpan di `ct0.txt` dalam profil).
- **Media DM**: dua jalur — proxy `ton.x.com` (DM biasa, stateless, full-res 4096×3072
  terverifikasi) dan cache in-memory untuk media E2EE XChat (TTL 15 menit, gambar saja,
  diisi oleh flow conversation di proses yang sama).
- **`fetch_dm_pin.py`**: script standalone (inbox/percakapan/media, `--save-media`,
  `--scan-limit`, `--browser`) — teruji live: scan 19 conv → 2 JPEG valid tersimpan.

## Hardening

- **dm_pin / auth_token di access log:** uvicorn access log default mencantumkan
  query string penuh — `?dm_pin=` terbukti bocor di log live. Fix berlapis:
  `uvicorn.access` dinonaktifkan programatik di `_setup_logging` (observability
  cukup dari AccessLogMiddleware path-only), `access_log=False` di Config
  `python3 main.py`, `--no-access-log` didokumentasikan untuk CLI. Produksi:
  pakai header `X-DM-Pin` (didukung semua endpoint XChat), bukan `?dm_pin=`.

- `requirements.txt` pin diperbaiki (pin lama tak ter-install di py3.9; minimum
  teruji: fastapi 0.128.8, curl_cffi 0.13.0, playwright 1.60.0).
- Pesan error jelas saat profil persist terkunci (server + script bareng).
- `/admin/stats` memuat `xchat_context_pool`.

## Batasan / risiko diketahui (bukan bug)

- Gate PIN XChat dikontrol server X — intermittently muncul walau profil persist
  ada; selalu siapkan `dm_pin`.
- Dekripsi E2EE murni-HTTP (tanpa browser) belum diimplementasi — perlu
  reverse-engineering protokol juicebox/PIN-KDF X.
- XChat video E2EE belum terekstrak (hanya `img[src]` blob:/ton).
- Profil persist menyimpan cookie sesi + kunci E2EE di disk — lindungi
  `.xchat_profiles/`; jangan commit; satu proses per profil.
