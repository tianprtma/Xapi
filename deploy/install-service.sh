#!/usr/bin/env bash
# Pasang unit systemd Xapi untuk LOKASI REPO INI (tidak hardcode path).
#
# Pemakaian:
#   sudo bash deploy/install-service.sh              # user = pemilik repo
#   sudo bash deploy/install-service.sh root         # paksa User=root (deploy di /root)
#   sudo bash deploy/install-service.sh root 8000    # user + port
#
# Setelah pasang: sama dengan `systemctl enable --now xapi` (auto-start saat boot
# + Restart=always saat crash). Perintah ini idempotent — aman dijalankan ulang.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${2:-8000}"

# Default user = pemilik direktori repo (Linux stat; fallback BSD; fallback id)
RUN_USER="${1:-$(stat -c '%u' "$REPO_DIR" 2>/dev/null | xargs -I{} getent passwd {} | cut -d: -f1 || true)}"
[ -n "$RUN_USER" ] || RUN_USER="$(stat -f '%Su' "$REPO_DIR" 2>/dev/null || id -un)"
RUN_GROUP="$(getent group "$RUN_USER" >/dev/null 2>&1 && id -gn "$RUN_USER" || id -gn)"

if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
    echo "PERINGATAN: $REPO_DIR/.venv belum ada. Jalankan dulu:"
    echo "  bash $REPO_DIR/deploy/deploy.sh"
fi

echo "── pasang unit: path=$REPO_DIR user=$RUN_USER group=$RUN_GROUP port=$PORT"

TMP_UNIT="$(mktemp)"
sed \
    -e "s#^WorkingDirectory=.*#WorkingDirectory=$REPO_DIR#" \
    -e "s#^Environment=HOME=.*#Environment=HOME=$REPO_DIR#" \
    -e "s#^User=.*#User=$RUN_USER#" \
    -e "s#^Group=.*#Group=$RUN_GROUP#" \
    -e "s#^# EnvironmentFile=-.*#EnvironmentFile=-$REPO_DIR/.env#" \
    -e "s#^ExecStart=.*#ExecStart=$REPO_DIR/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port $PORT --no-access-log#" \
    "$REPO_DIR/deploy/xapi.service" > "$TMP_UNIT"

sudo install -m 0644 "$TMP_UNIT" /etc/systemd/system/xapi.service
rm -f "$TMP_UNIT"

sudo systemctl daemon-reload
sudo systemctl enable --now xapi
echo "── terpasang & dijalankan. Cek: systemctl status xapi --no-pager"
echo "    health: curl -s http://127.0.0.1:$PORT/health"
