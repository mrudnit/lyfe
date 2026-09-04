#!/usr/bin/env bash
# Start the DJ live screen.
set -e
cd "$(dirname "$0")"
exec .venv/bin/python -m uvicorn lyfe.web.app:app \
  --host "${WEB_HOST:-0.0.0.0}" --port "${WEB_PORT:-8000}"
