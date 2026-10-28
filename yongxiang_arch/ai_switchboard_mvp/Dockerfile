FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql postgresql-contrib ca-certificates gzip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir psycopg2-binary "psycopg[binary]"
WORKDIR /app
COPY . /app
RUN chmod +x /app/entrypoint.sh && service postgresql start && \
    su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='box'\" | grep -q 1 || psql -c \"CREATE ROLE box WITH SUPERUSER LOGIN;\"" && \
    su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='yongxiang_plumb_r39_clone'\" | grep -q 1 || createdb -O box yongxiang_plumb_r39_clone" && \
    gunzip -c /app/seed_switchboard.sql.gz | su - postgres -c "psql -d yongxiang_plumb_r39_clone -q" && \
    su - postgres -c "psql -d yongxiang_plumb_r39_clone -c \"UPDATE public.org_settings SET org_mode = 'shadow'; DELETE FROM public.auth_state; DELETE FROM public.user_session;\"" && \
    service postgresql stop
ENV PORT=8080
ENV SWITCHBOARD_PG_DSN="postgresql://box@127.0.0.1:5432/yongxiang_plumb_r39_clone"
ENV SMTP_HOST=""
ENV SMTP_PASS=""
ENV SMTP_DISABLED="1"
EXPOSE 8080
CMD ["bash", "/app/entrypoint.sh"]
