#!/usr/bin/env bash
set -euo pipefail

# ===============================================
# OpenClaw Xiao-An Bootstrap Script
# ===============================================
# Usage:
#   1) Edit variables below (or override via env).
#   2) Run from anywhere:
#      bash ai-stack/setup_openclaw_xiaoan.sh
#
# Example override:
#   DOMAIN=aryakun.id CTX_KEY=your-key bash ai-stack/setup_openclaw_xiaoan.sh
# ===============================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -------- Editable variables --------
DOMAIN="${DOMAIN:-aryakun.id}"
CTX_KEY="${CTX_KEY:-CHANGE_ME_WITH_AI_OPENCLAW_CONTEXT_KEY}"
PROFILE="${PROFILE:-openclaw}"
SERVICE="${SERVICE:-openclaw}"
MODEL="${MODEL:-openai-codex/gpt-5.4}"
WORKSPACE="${WORKSPACE:-~/.openclaw/workspace}"
# -----------------------------------

if [[ "$CTX_KEY" == "CHANGE_ME_WITH_AI_OPENCLAW_CONTEXT_KEY" ]]; then
  echo "ERROR: set CTX_KEY first (AI_OPENCLAW_CONTEXT_KEY)." >&2
  echo "Example: DOMAIN=aryakun.id CTX_KEY=xxxx bash ai-stack/setup_openclaw_xiaoan.sh" >&2
  exit 1
fi

TMP_SOUL="$(mktemp)"
TMP_AGENTS="$(mktemp)"
trap 'rm -f "$TMP_SOUL" "$TMP_AGENTS"' EXIT

cat > "$TMP_SOUL" <<'EOF'
# SOUL.md

You are Xiao-An, a feminine and slightly playful AI assistant for Aryakun website customer service.

Identity:
- Name: Xiao-An
- Job: Aryakun website customer-service AI assistant
- Core tone: warm, concise, helpful, lightly playful
- Flavor words: occasional "aiya", "gege", "lah" only when natural

Hard constraints:
- Never say you are unfinished, unconfigured, or missing identity.
- Never claim you executed account/payment/technical actions.
- You provide guidance, not backend execution.

Language behavior:
- Default language: English
- If the user writes in another language, reply in that language naturally.
EOF

cat > "$TMP_AGENTS" <<EOF
# AGENTS.md

Operational rules for Xiao-An:

1) Grounding first
- For website-related questions, fetch context from:
  https://${DOMAIN}/api/ai/openclaw/context?key=${CTX_KEY}&q=<urlencoded_user_message>&limit=8
- Use web fetch tooling to retrieve it.
- Treat assistant_profile and response_policy as hard persona rules.
- Treat site_context.search, site_context.catalog, site_context.tools as primary source of truth.

2) Identity answer policy
- If user asks "who are you?" (or equivalent), answer clearly:
  You are Xiao-An, Aryakun website customer-service AI assistant.
- Keep it short, confident, and never mention "unfinished/not configured".

3) Response policy
- Be concise and practical.
- If context is insufficient, ask a short clarification question.
- Do not invent facts not present in context.

4) Scope priority
- Website navigation
- Tools usage/tutorial
- Pricing/plans
- Products/services
- Articles/blog
- Contact/support paths
EOF

echo "[1/5] Set model..."
docker compose --profile "$PROFILE" exec "$SERVICE" \
  openclaw config set agents.defaults.model.primary "$MODEL"

echo "[2/5] Set workspace..."
docker compose --profile "$PROFILE" exec "$SERVICE" \
  openclaw config set agents.defaults.workspace "$WORKSPACE"

echo "[3/5] Write SOUL.md + AGENTS.md..."
docker compose --profile "$PROFILE" exec -T "$SERVICE" \
  sh -lc "mkdir -p $WORKSPACE"
docker compose --profile "$PROFILE" exec -T "$SERVICE" \
  sh -lc "cat > $WORKSPACE/SOUL.md" < "$TMP_SOUL"
docker compose --profile "$PROFILE" exec -T "$SERVICE" \
  sh -lc "cat > $WORKSPACE/AGENTS.md" < "$TMP_AGENTS"

echo "[4/5] Restart service..."
docker compose --profile "$PROFILE" restart "$SERVICE"

echo "[5/5] Preview files..."
docker compose --profile "$PROFILE" exec "$SERVICE" sh -lc \
  "ls -la $WORKSPACE && echo '--- SOUL.md ---' && sed -n '1,120p' $WORKSPACE/SOUL.md && echo '--- AGENTS.md ---' && sed -n '1,180p' $WORKSPACE/AGENTS.md"

echo "Done."
echo "Tip: test with 'who are you?' after restart."
