FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql postgresql-contrib ca-certificates gzip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir psycopg2-binary "psycopg[binary]"
WORKDIR /app
COPY . /app
RUN chmod +x /app/entrypoint.sh && \
    sed -i 's/peer/trust/g; s/scram-sha-256/trust/g; s/md5/trust/g' /etc/postgresql/*/main/pg_hba.conf && \
    service postgresql start && \
    su - postgres -c "psql -c \"CREATE ROLE box WITH SUPERUSER LOGIN;\" || true" && \
    su - postgres -c "psql -c \"CREATE ROLE plumb_app WITH SUPERUSER LOGIN;\" || true" && \
    su - postgres -c "psql -c \"CREATE ROLE r47_workbench WITH SUPERUSER LOGIN;\" || true" && \
    su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='yongxiang_plumb_r39_clone'\" | grep -q 1 || createdb -O box yongxiang_plumb_r39_clone" && \
    gunzip -c /app/seed_switchboard_clean.sql.gz | su - postgres -c "psql -d yongxiang_plumb_r39_clone -q" && \
    su - postgres -c "psql -d yongxiang_plumb_r39_clone -c \"UPDATE public.org_mode SET mode = 'shadow'; DELETE FROM public.oauth_state; DELETE FROM public.api_session;\"" && \
    rm -f /app/seed_switchboard_clean.sql.gz && \
    service postgresql stop
ENV PORT=8080
ENV SWITCHBOARD_PG_DSN="postgresql://box@127.0.0.1:5432/yongxiang_plumb_r39_clone"
ENV SMTP_HOST=""
ENV SMTP_PASS=""
ENV SMTP_DISABLED="1"
EXPOSE 8080 5188
CMD ["bash", "/app/entrypoint.sh"]
