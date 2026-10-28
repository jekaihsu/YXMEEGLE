#!/usr/bin/env bash
set -euo pipefail
echo "[entrypoint] Starting PostgreSQL 127.0.0.1:5432..."
mkdir -p /var/run/postgresql /tmp
chown -R postgres:postgres /var/run/postgresql /var/lib/postgresql /var/log/postgresql
chmod 775 /var/run/postgresql
service postgresql start || {
  cat /var/log/postgresql/*.log || true
  exit 1
}

for i in $(seq 1 30); do
  if pg_isready -h 127.0.0.1 -p 5432 -U box -d yongxiang_plumb_r39_clone >/dev/null 2>&1; then
    echo "[entrypoint] PostgreSQL yongxiang_plumb_r39_clone is ready."
    break
  fi
  sleep 0.2
done

case "${PORT:-}" in
  ''|*[!0-9]*) export PORT=8080 ;;
esac
export PGDATABASE="yongxiang_plumb_r39_clone"
export SWITCHBOARD_PG_DSN="postgresql://box@127.0.0.1:5432/yongxiang_plumb_r39_clone"
export SMTP_HOST=""
export SMTP_PASS=""
export SMTP_DISABLED="1"
cd /app
echo "[entrypoint] Starting switchboard_ui_server.py on PORT=${PORT} and 5188..."
exec python3 -u /app/switchboard_ui_server.py
