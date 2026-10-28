#!/usr/bin/env bash
set -euo pipefail
PG_BIN="$(ls -d /usr/lib/postgresql/*/bin | head -n 1)"
su - postgres -c "${PG_BIN}/pg_ctl -D /var/lib/postgresql/switchboard_data -l /tmp/postgres.log -o '-c listen_addresses=127.0.0.1 -p 5432' start"
for i in $(seq 1 30); do
  if pg_isready -h 127.0.0.1 -p 5432 -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
export PORT="${PORT:-8080}"
export PGDATABASE="yongxiang_plumb_r39_clone"
export SMTP_HOST=""
export SMTP_PASS=""
export SMTP_DISABLED="1"
cd /app
exec python3 /app/switchboard_ui_server.py
