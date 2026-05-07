#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AI_STACK_DIR="${AI_STACK_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
cd "$AI_STACK_DIR"

bash "$SCRIPT_DIR/openclaw_preflight.sh"

PROFILE="${PROFILE:-openclaw}"
SERVICE="${SERVICE:-openclaw}"
PLUGIN_ID="${PLUGIN_ID:-xiaoan-dm-gate}"
PLUGIN_PATH="${PLUGIN_PATH:-/opt/openclaw/plugins/xiaoan-dm-gate}"
FORCE_REINSTALL="${FORCE_REINSTALL:-1}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-60}"
WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-2}"

wait_for_service_running() {
  local elapsed=0
  while true; do
    if docker compose --profile "$PROFILE" ps --status running "$SERVICE" | grep -q "$SERVICE"; then
      return 0
    fi
    if (( elapsed >= WAIT_TIMEOUT_SECONDS )); then
      echo "ERROR: service '$SERVICE' is not running after ${WAIT_TIMEOUT_SECONDS}s." >&2
      if ! docker compose --profile "$PROFILE" ps "$SERVICE"; then
        echo "WARN: failed to print docker compose status for '$SERVICE'." >&2
      fi
      return 1
    fi
    sleep "$WAIT_INTERVAL_SECONDS"
    elapsed=$((elapsed + WAIT_INTERVAL_SECONDS))
  done
}

run_openclaw() {
  wait_for_service_running
  docker compose --profile "$PROFILE" exec -T "$SERVICE" openclaw "$@"
}

run_openclaw_optional() {
  local output
  if output="$(run_openclaw "$@" 2>&1)"; then
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    return 0
  fi

  echo "WARN: optional OpenClaw command failed: openclaw $*" >&2
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output" >&2
  fi
  return 0
}

echo "[1/8] Preflight plugin path..."
wait_for_service_running
docker compose --profile "$PROFILE" exec -T "$SERVICE" sh -lc \
  "test -d '$PLUGIN_PATH' && test -f '$PLUGIN_PATH/index.js' && test -f '$PLUGIN_PATH/package.json'"
docker compose --profile "$PROFILE" exec -T "$SERVICE" sh -lc \
  "echo 'Plugin source:' && cat '$PLUGIN_PATH/package.json'"

echo "[2/8] Uninstall old plugin instance (safe)..."
run_openclaw_optional plugins disable "$PLUGIN_ID"
if [[ "$FORCE_REINSTALL" == "1" || "$FORCE_REINSTALL" == "true" || "$FORCE_REINSTALL" == "yes" ]]; then
  run_openclaw_optional plugins uninstall "$PLUGIN_ID" --keep-files
else
  echo "FORCE_REINSTALL disabled, skip uninstall."
fi

echo "[3/8] Install plugin from local path..."
run_openclaw plugins install -l "$PLUGIN_PATH"

echo "[4/8] Enable plugin..."
run_openclaw plugins enable "$PLUGIN_ID"

echo "[5/8] Apply WhatsApp channel policy for DM gate..."
run_openclaw_optional config unset channels.whatsapp.messagePrefix
run_openclaw_optional config unset channels.whatsapp.accounts.default.messagePrefix
run_openclaw config set channels.whatsapp.sendReadReceipts false
run_openclaw config set channels.whatsapp.accounts.default.sendReadReceipts false
run_openclaw config set channels.whatsapp.reactionLevel off
run_openclaw config set channels.whatsapp.accounts.default.reactionLevel off
run_openclaw_optional config unset channels.telegram.messagePrefix
run_openclaw_optional config unset channels.telegram.accounts.default.messagePrefix
run_openclaw_optional config unset channels.discord.messagePrefix
run_openclaw_optional config unset channels.discord.accounts.default.messagePrefix

echo "[6/8] Restart OpenClaw..."
docker compose --profile "$PROFILE" restart "$SERVICE"
wait_for_service_running

echo "[7/8] Verify plugin status..."
run_openclaw plugins inspect "$PLUGIN_ID"

echo "[8/8] Show enabled plugins snapshot..."
run_openclaw plugins list --enabled
echo "Done."
echo "Validation tips:"
echo "  1) Send DM without /ia => should reply reminder once, then silent."
echo "  2) Send DM with /ia => should reach AI."
echo "  3) During cooldown, owner should still see unread chat (sendReadReceipts=false)."
echo "Tip: watch logs with:"
echo "  docker compose --profile $PROFILE logs -f $SERVICE"
