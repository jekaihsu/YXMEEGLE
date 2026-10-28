FROM python:3.12-slim-bookworm

WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic httpx
COPY . /app

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
