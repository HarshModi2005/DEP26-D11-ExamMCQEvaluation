#!/usr/bin/env bash
set -euo pipefail

# Always run from this directory (backend/), no matter who invokes us.
cd "$(dirname "$0")"

# Railway-friendly Google credentials bootstrap:
# 1) GOOGLE_CREDENTIALS_JSON (raw JSON string)
# 2) GOOGLE_CREDENTIALS_BASE64 (base64-encoded JSON)
# 3) GOOGLE_APPLICATION_CREDENTIALS (pre-existing file path)
if [ -n "${GOOGLE_CREDENTIALS_JSON:-}" ]; then
  printf '%s' "${GOOGLE_CREDENTIALS_JSON}" > /tmp/gcp-service-account.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-service-account.json
elif [ -n "${GOOGLE_CREDENTIALS_BASE64:-}" ]; then
  # Strip whitespace/newlines — pasted secrets and `base64` without -w0 often break GNU base64.
  _b64=$(printf '%s' "${GOOGLE_CREDENTIALS_BASE64}" | tr -d '\n\r\t ')
  if ! printf '%s' "${_b64}" | base64 -d >/tmp/gcp-service-account.json 2>/dev/null; then
    echo "ERROR: GOOGLE_CREDENTIALS_BASE64 could not be decoded (invalid base64)." >&2
    echo "Fix: paste one line only, or regenerate:  openssl base64 -A -in key.json" >&2
    echo "Or use GOOGLE_CREDENTIALS_JSON with the raw JSON instead." >&2
    exit 1
  fi
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-service-account.json
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
