#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

bash ./openclaw_preflight.sh

docker compose --profile openclaw up -d openclaw_init_permissions
docker compose --profile openclaw up -d "$@"
