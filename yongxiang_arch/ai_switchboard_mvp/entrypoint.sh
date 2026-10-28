#!/usr/bin/env bash
set -euo pipefail
echo "[entrypoint] Initializing runtime directories..."
PG_BIN="$(ls -d /usr/lib/postgresql/*/bin | head -n 1)"
mkdir -p /var/run/postgresql /tmp
chown -R postgres:postgres /var/run/postgresql /var/lib/postgresql/switchboard_data
chmod 775 /var/run/postgresql
chmod 700 /var/lib/postgresql/switchboard_data
rm -f /var/lib/postgresql/switchboard_data/postmaster.pid

echo "[entrypoint] Starting PostgreSQL 127.0.0.1:5432..."
su -s /bin/bash postgres -c "${PG_BIN}/pg_ctl -D /var/lib/postgresql/switchboard_data -l /tmp/postgres.log -o '-c listen_addresses=127.0.0.1 -p 5432 -c unix_socket_directories=/var/run/postgresql,/tmp -c shared_buffers=32MB -c dynamic_shared_memory_type=mmap' start" || {
  echo "[entrypoint] pg_ctl start failed; dumping /tmp/postgres.log:"
  cat /tmp/postgres.log || true
  exit 1
}

for i in $(seq 1 30); do
  if pg_isready -h 127.0.0.1 -p 5432 -U postgres >/dev/null 2>&1; then
    echo "[entrypoint] PostgreSQL is ready."
    break
  fi
  sleep 0.2
done

case "${PORT:-}" in
  ''|*[!0-9]*) export PORT=8080 ;;
esac
export PGDATABASE="yongxiang_plumb_r39_clone"
export SMTP_HOST=""
export SMTP_PASS=""
export SMTP_DISABLED="1"
cd /app
echo "[entrypoint] Starting switchboard_ui_server.py on PORT=${PORT} and 5188..."
exec python3 -u /app/switchboard_ui_server.py
