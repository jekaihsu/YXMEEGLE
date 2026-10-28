FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql postgresql-contrib ca-certificates gzip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir psycopg2-binary "psycopg[binary]"

WORKDIR /app
COPY . /app

RUN PG_BIN="$(ls -d /usr/lib/postgresql/*/bin | head -n 1)" \
    && mkdir -p /var/lib/postgresql/switchboard_data /var/run/postgresql \
    && chown -R postgres:postgres /var/lib/postgresql/switchboard_data /var/run/postgresql \
    && su - postgres -c "${PG_BIN}/initdb -D /var/lib/postgresql/switchboard_data --encoding=UTF8 --locale=C.UTF-8 --auth-local=trust --auth-host=trust" \
    && su - postgres -c "${PG_BIN}/pg_ctl -D /var/lib/postgresql/switchboard_data -l /tmp/pg_init.log -o '-c listen_addresses=127.0.0.1 -p 5432' start" \
    && psql -h 127.0.0.1 -U postgres -d postgres -c "ALTER USER postgres WITH PASSWORD 'postgres';" \
    && psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE yongxiang_plumb_r39_clone;" \
    && psql -h 127.0.0.1 -U postgres -d yongxiang_plumb_r39_clone -c "CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS btree_gist;" \
    && zcat /app/seed_switchboard_clean.sql.gz | psql -X -q -h 127.0.0.1 -U postgres -d yongxiang_plumb_r39_clone \
    && psql -h 127.0.0.1 -U postgres -d yongxiang_plumb_r39_clone -c "SELECT (SELECT count(*) FROM public.employee WHERE org_id='YX' AND employment_status='active' AND identity_confirmed) AS active_emp, (SELECT mode FROM public.org_mode WHERE org_id='YX') AS org_mode;" \
    && su - postgres -c "${PG_BIN}/pg_ctl -D /var/lib/postgresql/switchboard_data stop" \
    && rm -f /app/seed_switchboard_clean.sql.gz

ENV PORT=8080
ENV SMTP_HOST=""
ENV SMTP_PASS=""
ENV SMTP_DISABLED="1"
EXPOSE 8080 5188
CMD ["/app/entrypoint.sh"]
