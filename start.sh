#!/usr/bin/env bash
set -euo pipefail
# Repo-root entry: delegate to backend script (works for local `bash ./start.sh` from project root).
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/backend/start.sh"
