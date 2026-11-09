#!/usr/bin/env bash
# Siapkan/update Xapi di VPS: git pull + venv + deps + Chromium + .env.
# Jalankan sebagai user service (HOME sudah menunjuk repo):
#   sudo -u xapi bash deploy/deploy.sh
# Restart service dilakukan TERPISAH (butuh sudo):
#   sudo systemctl restart xapi
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # root repo

echo "── git pull (ff-only)"
git pull --ff-only origin main

# HOME = repo: cache Chromium Playwright konsisten dengan Environment=HOME=
# di unit systemd (tanpa ini, browser terinstal di /root/.cache tapi service
# mencarinya di repo/.cache → "Executable doesn't exist").
export HOME="$PWD"

echo "── venv + dependencies"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "── Chromium untuk Playwright (wajib utk XChat E2EE)"
.venv/bin/python -m playwright install chromium

# .env minimal — TIDAK menimpa yang sudah ada (isi ADMIN_TOKEN dst manual)
if [ ! -f .env ]; then
    cp .env.example .env
    echo "── .env dibuat dari contoh — EDIT sebelum start:"
    echo "   nano .env   (ADMIN_TOKEN, ALLOW_QUERY_AUTH=0, ENABLE_RAW=0,"
    echo "               PLAYWRIGHT_ENABLED=1, PROXY_LIST= kosong/valid)"
fi

echo "── selesai"
if systemctl list-unit-files 2>/dev/null | grep -q "^xapi.service"; then
    echo "restart + cek health:  sudo systemctl restart xapi && sleep 3 && curl -s http://127.0.0.1:8000/health"
else
    echo "langkah berikutnya (runbook): pasang unit systemd lalu enable --now"
fi
