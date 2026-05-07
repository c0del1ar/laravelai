#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AI_STACK_DIR="${AI_STACK_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
cd "$AI_STACK_DIR"

bash "$SCRIPT_DIR/openclaw_preflight.sh"

docker compose --profile openclaw up -d openclaw_init_permissions
docker compose --profile openclaw up -d "$@"
