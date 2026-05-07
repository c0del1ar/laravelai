#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AI_STACK_DIR="${AI_STACK_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
cd "$AI_STACK_DIR"

bash "$SCRIPT_DIR/openclaw_preflight.sh"

PROFILE="${PROFILE:-openclaw}"
SERVICE="${SERVICE:-openclaw}"
TOOLS_ALLOW_JSON="${TOOLS_ALLOW_JSON:-[\"session_status\",\"group:web\",\"group:memory\"]}"
TOOLS_DENY_JSON="${TOOLS_DENY_JSON:-[\"exec\",\"terminal\",\"shell\",\"run\",\"read\",\"write\",\"edit\",\"apply_patch\",\"browser\",\"canvas\"]}"

set_openclaw_config() {
  local key="$1"
  local value="$2"
  local output
  if output="$(docker compose --profile "$PROFILE" exec -T "$SERVICE" \
    sh -lc "openclaw config set \"$key\" '$value'" 2>&1)"; then
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    return 0
  fi

  echo "WARN: failed to set OpenClaw config key '$key'." >&2
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output" >&2
  fi
  return 1
}

set_first_supported_key() {
  local value="$1"
  shift
  local key
  for key in "$@"; do
    if set_openclaw_config "$key" "$value"; then
      echo "Applied: $key"
      return 0
    fi
  done
  return 1
}

echo "[1/3] Applying OpenClaw restricted CS tool policy..."
if ! set_first_supported_key "$TOOLS_ALLOW_JSON" \
  "agents.defaults.tools.allow" \
  "tools.allow"; then
  echo "WARN: cannot set tools allow-list automatically on this OpenClaw version."
fi

if ! set_first_supported_key "$TOOLS_DENY_JSON" \
  "agents.defaults.tools.deny" \
  "tools.deny"; then
  echo "WARN: cannot set tools deny-list automatically on this OpenClaw version."
fi

echo "[2/3] Restarting OpenClaw..."
docker compose --profile "$PROFILE" restart "$SERVICE"

echo "[3/3] Done."
echo "If your OpenClaw version uses different config keys, run:"
echo "  docker compose --profile $PROFILE exec $SERVICE openclaw config list"
echo "Then map equivalent keys for tools allow/deny."
