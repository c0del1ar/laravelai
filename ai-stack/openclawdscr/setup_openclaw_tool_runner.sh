#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AI_STACK_DIR="${AI_STACK_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
cd "$AI_STACK_DIR"

bash "$SCRIPT_DIR/openclaw_preflight.sh"

PROFILE="${PROFILE:-openclaw}"
SERVICE="${SERVICE:-openclaw}"
PLUGIN_ID="${PLUGIN_ID:-xiaoan-tool-runner}"
PLUGIN_PATH="${PLUGIN_PATH:-/opt/openclaw/plugins/xiaoan-tool-runner}"
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

dump_diagnostics() {
  local title="${1:-diagnostics}"
  local container_id=""
  echo "---- $title: docker compose ps ----" >&2
  if ! docker compose --profile "$PROFILE" ps "$SERVICE" >&2; then
    echo "WARN: failed to print docker compose status for '$SERVICE'." >&2
  fi
  if container_id="$(docker compose --profile "$PROFILE" ps -q "$SERVICE" 2>&1)"; then
    if [[ -n "$container_id" ]]; then
      echo "---- $title: docker inspect state ----" >&2
      if ! docker inspect \
        --format 'status={{.State.Status}} running={{.State.Running}} oom_killed={{.State.OOMKilled}} exit_code={{.State.ExitCode}} error={{.State.Error}}' \
        "$container_id" >&2; then
        echo "WARN: failed to inspect container '$container_id'." >&2
      fi
    fi
  else
    echo "WARN: failed to resolve container id for '$SERVICE': $container_id" >&2
  fi
  echo "---- $title: recent OpenClaw logs ----" >&2
  if ! docker compose --profile "$PROFILE" logs --tail=120 "$SERVICE" >&2; then
    echo "WARN: failed to print recent OpenClaw logs." >&2
  fi
  echo "---- $title: plugin inspect ----" >&2
  if ! docker compose --profile "$PROFILE" exec -T "$SERVICE" openclaw plugins inspect "$PLUGIN_ID" >&2; then
    echo "WARN: failed to inspect plugin '$PLUGIN_ID'." >&2
  fi
}

run_openclaw_required() {
  local output
  if output="$(run_openclaw "$@" 2>&1)"; then
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    return 0
  fi

  local status=$?
  echo "ERROR: required OpenClaw command failed with exit code $status: openclaw $*" >&2
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output" >&2
  fi
  dump_diagnostics "failure after: openclaw $*"
  return "$status"
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

echo "[1/6] Preflight plugin path..."
wait_for_service_running
docker compose --profile "$PROFILE" exec -T "$SERVICE" sh -lc \
  "test -d '$PLUGIN_PATH' && test -f '$PLUGIN_PATH/index.js' && test -f '$PLUGIN_PATH/package.json'"
docker compose --profile "$PROFILE" exec -T "$SERVICE" sh -lc \
  "echo 'Plugin source:' && cat '$PLUGIN_PATH/package.json'"

echo "[2/6] Uninstall old plugin instance (safe)..."
run_openclaw_optional plugins disable "$PLUGIN_ID"
run_openclaw_optional config unset "plugins.entries.$PLUGIN_ID"
if [[ "$FORCE_REINSTALL" == "1" || "$FORCE_REINSTALL" == "true" || "$FORCE_REINSTALL" == "yes" ]]; then
  run_openclaw_optional plugins uninstall "$PLUGIN_ID" --keep-files
else
  echo "FORCE_REINSTALL disabled, skip uninstall."
fi

echo "[3/6] Install plugin from local path..."
run_openclaw_required plugins install -l "$PLUGIN_PATH"

echo "[4/6] Enable plugin..."
run_openclaw_required plugins enable "$PLUGIN_ID"

echo "[5/6] Restart OpenClaw..."
docker compose --profile "$PROFILE" restart "$SERVICE"
wait_for_service_running

echo "[6/6] Verify plugin status..."
run_openclaw_required plugins inspect "$PLUGIN_ID"
echo "Done."
echo "Validation tips:"
echo "  1) Ensure cli-stack is running: cd ../cli-stack && docker compose up -d --build"
echo "  2) Send DM: /tool"
echo "  3) Send DM: /tool echo hello"
