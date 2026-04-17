# Backend API — repo root context (docker build -f Dockerfile .)
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps before copying full tree (better layer cache)
COPY backend/requirements.txt ./backend/requirements.txt
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir -r backend/requirements.txt

COPY . .

WORKDIR /app/backend
EXPOSE 8000

# Match local / PaaS convention: PORT optional
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
