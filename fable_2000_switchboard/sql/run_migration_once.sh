#!/usr/bin/env bash
# Usage: run_migration_once.sh <db> <migration.sql> [log]
# Skips the file if public.schema_migration already records it (name = file basename without .sql).
set -euo pipefail
DB="$1"; F="$2"; LOG="${3:-/dev/stdout}"
NAME="$(basename "$F" .sql)"
DONE=$(psql -d "$DB" -Atc "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='schema_migration'" )
if [[ "$DONE" == "1" ]] && [[ "$(psql -d "$DB" -Atc "SELECT 1 FROM public.schema_migration WHERE name='${NAME//\'/}'")" == "1" ]]; then
  echo "SKIP: $NAME already applied on $DB" | tee -a "$LOG"; exit 0
fi
psql -v ON_ERROR_STOP=1 -d "$DB" -f "$F" >>"$LOG" 2>&1
echo "APPLIED: $NAME on $DB" | tee -a "$LOG"
