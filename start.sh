#!/usr/bin/env bash
set -euo pipefail

cd backend

# Railway-friendly Google credentials bootstrap:
# 1) GOOGLE_CREDENTIALS_JSON (raw JSON string)
# 2) GOOGLE_CREDENTIALS_BASE64 (base64-encoded JSON)
# 3) GOOGLE_APPLICATION_CREDENTIALS (pre-existing file path)
if [ -n "${GOOGLE_CREDENTIALS_JSON:-}" ]; then
  printf '%s' "${GOOGLE_CREDENTIALS_JSON}" > /tmp/gcp-service-account.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-service-account.json
elif [ -n "${GOOGLE_CREDENTIALS_BASE64:-}" ]; then
  printf '%s' "${GOOGLE_CREDENTIALS_BASE64}" | base64 --decode > /tmp/gcp-service-account.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-service-account.json
fi

# Railway injects PORT at runtime.
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
