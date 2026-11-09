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

# ── Python 3.11 (wajib; override: PYTHON_BIN=python3.x bash deploy/deploy.sh)
# PENTING: prefer /usr/bin/python3.11 (paket deadsnakes) — python3.11 di PATH
# bisa saja build kustom tanpa modul ensurepip, yang membuat venv TANPA pip.
if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x /usr/bin/python3.11 ]; then
        PYTHON_BIN=/usr/bin/python3.11
    else
        PYTHON_BIN=python3.11
    fi
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: $PYTHON_BIN tidak ditemukan."
    echo "  Ubuntu 22.04/24.04:"
    echo "    sudo apt update && sudo apt install -y software-properties-common"
    echo "    sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt update"
    echo "    sudo apt install -y python3.11 python3.11-venv"
    echo "  Atau paksa versi lain: PYTHON_BIN=python3 bash deploy/deploy.sh"
    exit 1
fi
EXPECTED_MM="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "── venv + dependencies (python $EXPECTED_MM — $("$PYTHON_BIN" -V 2>&1); bin: $PYTHON_BIN)"

# Modul ensurepip wajib ada agar pip masuk ke venv. Build kustom sering
# tidak menyertakannya (gejala: venv terbuat tapi .venv/bin/pip tidak ada).
if ! "$PYTHON_BIN" -c "import ensurepip" >/dev/null 2>&1; then
    echo "   PERINGATAN: $PYTHON_BIN tidak punya modul ensurepip."
    echo "   Coba /usr/bin/python3.11 (deadsnakes) atau install paket:"
    echo "     sudo apt install -y python${EXPECTED_MM}-venv"
fi

# venv lama dengan versi berbeda / tanpa pip / tanpa bin/python → dibuat ulang
if [ -d .venv ]; then
    VENV_MM="$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)"
    if [ "$VENV_MM" != "$EXPECTED_MM" ]; then
        echo "   venv lama = Python $VENV_MM, target = $EXPECTED_MM → dibuat ulang"
        rm -rf .venv
    elif [ ! -x .venv/bin/python ]; then
        echo "   .venv tidak lengkap (tanpa bin/python) → dibuat ulang"
        rm -rf .venv
    elif [ ! -x .venv/bin/pip ]; then
        echo "   .venv ada tapi tanpa pip → dibuat ulang"
        rm -rf .venv
    fi
fi
[ -d .venv ] || "$PYTHON_BIN" -m venv .venv

# Kalau masih tanpa pip: coba ensurepip di dalam venv, lalu diagnosa jelas.
if [ ! -x .venv/bin/pip ]; then
    echo "   pip belum ada di venv — mencoba ensurepip…"
    .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
fi
if [ ! -x .venv/bin/pip ]; then
    echo "ERROR: venv tidak memiliki pip."
    echo "  Diagnosa:"
    echo "    command -v $PYTHON_BIN"
    echo "    $PYTHON_BIN -c 'import ensurepip; print(\"ensurepip OK\")'"
    echo "  Perbaiki (paket venv untuk Python $EXPECTED_MM):"
    echo "    sudo apt update && sudo apt install -y python${EXPECTED_MM}-venv"
    echo "  Lalu ulangi dengan interpreter apt:"
    echo "    PYTHON_BIN=/usr/bin/python3.11 bash deploy/deploy.sh"
    rm -rf .venv   # buang venv parsial agar run berikutnya bersih
    exit 1
fi
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
