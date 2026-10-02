FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 UPLOAD_DIR=/data/uploads APP_ENV=production DEMO_MODE=false
WORKDIR /app
COPY backend/requirements.lock ./backend/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r backend/requirements.lock
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY deployment/source-tables.json ./deployment/source-tables.json
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN groupadd --gid 10001 workbench && useradd --uid 10001 --gid 10001 --no-create-home workbench \
    && mkdir -p /data/uploads /data/backups && chown 10001:10001 /data/uploads /data/backups
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/api/health',timeout=4)"
CMD ["python", "scripts/run_service.py"]
