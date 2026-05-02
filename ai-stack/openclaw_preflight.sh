#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

KEY="${OPENCLAW_WEBHOOK_KEY:-}"
if [[ -z "$KEY" && -f ".env" ]]; then
  KEY="$(awk -F= '/^OPENCLAW_WEBHOOK_KEY=/{sub(/^[^=]*=/, "", $0); print; exit}' .env)"
fi
KEY="${KEY%$'\r'}"
KEY="${KEY#\"}"
KEY="${KEY%\"}"
KEY="${KEY#\'}"
KEY="${KEY%\'}"

LOWER_KEY="$(printf '%s' "$KEY" | tr '[:upper:]' '[:lower:]')"

if [[ -z "$KEY" ]]; then
  echo "ERROR: OPENCLAW_WEBHOOK_KEY is empty. Refusing to run OpenClaw profile." >&2
  echo "Set OPENCLAW_WEBHOOK_KEY in ai-stack/.env first." >&2
  exit 1
fi

if [[ "$LOWER_KEY" == "change-this-openclaw-key" || "$LOWER_KEY" == *"change-this"* || "$LOWER_KEY" == *"changeme"* ]]; then
  echo "ERROR: OPENCLAW_WEBHOOK_KEY still uses placeholder value. Refusing to run OpenClaw profile." >&2
  echo "Set a real random key in ai-stack/.env first." >&2
  exit 1
fi

if ! docker compose --profile openclaw config --services | grep -qx "openclaw"; then
  echo "ERROR: openclaw service not found in docker compose profile 'openclaw'." >&2
  exit 1
fi
