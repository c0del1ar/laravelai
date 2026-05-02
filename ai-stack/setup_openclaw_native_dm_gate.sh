#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

bash ./openclaw_preflight.sh

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
      docker compose --profile "$PROFILE" ps "$SERVICE" || true
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

run_openclaw_tolerant() {
  run_openclaw "$@" >/dev/null 2>&1 || true
}

echo "[1/8] Preflight plugin path..."
wait_for_service_running
docker compose --profile "$PROFILE" exec -T "$SERVICE" sh -lc \
  "test -d '$PLUGIN_PATH' && test -f '$PLUGIN_PATH/index.js' && test -f '$PLUGIN_PATH/package.json'"
docker compose --profile "$PROFILE" exec -T "$SERVICE" sh -lc \
  "echo 'Plugin source:' && cat '$PLUGIN_PATH/package.json'"

echo "[2/8] Uninstall old plugin instance (safe)..."
run_openclaw_tolerant plugins disable "$PLUGIN_ID"
if [[ "$FORCE_REINSTALL" == "1" || "$FORCE_REINSTALL" == "true" || "$FORCE_REINSTALL" == "yes" ]]; then
  run_openclaw_tolerant plugins uninstall "$PLUGIN_ID" --keep-files
else
  echo "FORCE_REINSTALL disabled, skip uninstall."
fi

echo "[3/8] Install plugin from local path..."
run_openclaw plugins install -l "$PLUGIN_PATH"

echo "[4/8] Enable plugin..."
run_openclaw plugins enable "$PLUGIN_ID"

echo "[5/8] Apply WhatsApp channel policy for DM gate..."
run_openclaw_tolerant config unset channels.whatsapp.messagePrefix
run_openclaw_tolerant config unset channels.whatsapp.accounts.default.messagePrefix
run_openclaw_tolerant config set channels.whatsapp.sendReadReceipts false
run_openclaw_tolerant config set channels.whatsapp.accounts.default.sendReadReceipts false
run_openclaw_tolerant config set channels.whatsapp.reactionLevel off
run_openclaw_tolerant config set channels.whatsapp.accounts.default.reactionLevel off
run_openclaw_tolerant config unset channels.telegram.messagePrefix
run_openclaw_tolerant config unset channels.telegram.accounts.default.messagePrefix
run_openclaw_tolerant config unset channels.discord.messagePrefix
run_openclaw_tolerant config unset channels.discord.accounts.default.messagePrefix

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
