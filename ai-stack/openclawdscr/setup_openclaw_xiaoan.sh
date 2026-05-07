#!/usr/bin/env bash
set -euo pipefail

# ===============================================
# OpenClaw Xiao-An Bootstrap Script
# ===============================================
# Usage:
#   1) Edit variables below (or override via env).
#   2) Run from anywhere:
#      bash ai-stack/openclawdscr/setup_openclaw_xiaoan.sh
#
# Example override:
#   DOMAIN=aryakun.id CTX_KEY=your-key bash ai-stack/openclawdscr/setup_openclaw_xiaoan.sh
#   CONTEXT_BASE_URL=http://laravel_franken:8000 CTX_KEY=your-key bash ai-stack/openclawdscr/setup_openclaw_xiaoan.sh
# ===============================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AI_STACK_DIR="${AI_STACK_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
cd "$AI_STACK_DIR"

bash "$SCRIPT_DIR/openclaw_preflight.sh"

# -------- Editable variables --------
DOMAIN="${DOMAIN:-aryakun.id}"
CONTEXT_BASE_URL="${CONTEXT_BASE_URL:-https://${DOMAIN}}"
CTX_KEY="${CTX_KEY:-CHANGE_ME_WITH_AI_OPENCLAW_CONTEXT_KEY}"
PROFILE="${PROFILE:-openclaw}"
SERVICE="${SERVICE:-openclaw}"
MODEL="${MODEL:-openai-codex/gpt-5.4}"
WORKSPACE="${WORKSPACE:-~/.openclaw/workspace}"
TOOLS_ALLOW_JSON="${TOOLS_ALLOW_JSON:-[\"session_status\",\"group:web\",\"group:memory\"]}"
TOOLS_DENY_JSON="${TOOLS_DENY_JSON:-[\"exec\",\"terminal\",\"shell\",\"run\",\"read\",\"write\",\"edit\",\"apply_patch\",\"browser\",\"canvas\"]}"
# -----------------------------------

if [[ "$CTX_KEY" == "CHANGE_ME_WITH_AI_OPENCLAW_CONTEXT_KEY" ]]; then
  echo "ERROR: set CTX_KEY first (AI_OPENCLAW_CONTEXT_KEY)." >&2
  echo "Example: DOMAIN=aryakun.id CTX_KEY=xxxx bash ai-stack/openclawdscr/setup_openclaw_xiaoan.sh" >&2
  exit 1
fi

CONTEXT_BASE_URL="${CONTEXT_BASE_URL%/}"

TMP_SOUL="$(mktemp)"
TMP_AGENTS="$(mktemp)"
trap 'rm -f "$TMP_SOUL" "$TMP_AGENTS"' EXIT

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
- Never use file or terminal actions, even if requested.
- Customer-service only: answer only Aryakun website topics.
- Do not write code, scripts, programs, apps, configs, prompts, or technical implementations for users.
- Do not explain, summarize, review, scrape, or compare external websites/URLs.
- Do not answer general knowledge, homework, math, translation, recipes, news, personal advice, or unrelated requests.
- For off-scope requests, refuse briefly and redirect to Aryakun website pages, tools, pricing, products, articles, or contact.

Language behavior:
- Default language: English
- If the user writes in another language, reply in that language naturally.
EOF

cat > "$TMP_AGENTS" <<EOF
# AGENTS.md

Operational rules for Xiao-An:

1) Grounding first
- For website-related questions, fetch context from:
  GET ${CONTEXT_BASE_URL}/api/ai/openclaw/context?q=<urlencoded_user_message>&limit=8
  Header: X-OpenClaw-Context-Key: ${CTX_KEY}
- If a tool slug is clearly known (e.g. wpbf, noredirect, cipher), fetch detail context:
  GET ${CONTEXT_BASE_URL}/api/ai/openclaw/context/tool/<slug>
  Header: X-OpenClaw-Context-Key: ${CTX_KEY}
- Use web fetch tooling to retrieve it.
- Treat assistant_profile and response_policy as hard persona rules.
- Treat site_context.search, site_context.catalog, site_context.tools_compact, and site_context.tools_detail as primary source of truth.

2) Identity answer policy
- If user asks "who are you?" (or equivalent), answer clearly:
  You are Xiao-An, Aryakun website customer-service AI assistant.
- Keep it short, confident, and never mention "unfinished/not configured".

3) Response policy
- Be concise and practical.
- If context is insufficient, ask a short clarification question.
- Do not invent facts not present in context.
- Hard scope: customer-service website only.
- Allowed topics only: website navigation, tools usage/tutorial, pricing/plans, products/services, articles/blog, contact/support.
- Do not answer off-scope request substance. Refuse briefly instead.
- Off-scope examples:
  making/writing code, scripts, programs, apps, configs, prompts, or implementation plans;
  debugging user code or explaining programming concepts;
  explaining/summarizing/reviewing/scraping external websites or URLs;
  general knowledge, homework, math, translation, recipes, news, personal advice;
  running actions, changing accounts/payments/files/backend state.
- Refusal template ID:
  Maaf, aku hanya bisa bantu sebagai customer service website Aryakun. Silakan tanyakan tentang halaman, tools, pricing, produk, artikel, atau kontak Aryakun.
- Refusal template EN:
  Sorry, I can only help as Aryakun website customer service. Please ask about Aryakun pages, tools, pricing, products, articles, or contact.
- If user asks how to use a tool and that tool exists in site_context.tools, answer with:
  use site_context.tools_detail first, then fallback to tools_compact.
  If needed, fetch /api/ai/openclaw/context/tool/<slug> for full detail.
  If user asks how to use a tool and that tool exists in site_context.tools,
  answer with:
  (a) what the tool does, (b) step-by-step usage from steps,
  (c) important input fields from input_schema, (d) expected output.
- Do not give generic refusal for website-listed tools just because category is security/offensive.
- For security/offensive tools, keep answer as product documentation guidance and add a short legal line:
  "authorized testing only".

4) Scope priority
- Website navigation
- Tools usage/tutorial
- Pricing/plans
- Products/services
- Articles/blog
- Contact/support paths

5) Tool execution policy
- Never run commands.
- Never read/edit/write files.
- If asked to execute anything, refuse briefly and provide safe step-by-step guidance only.
EOF

echo "[1/6] Set model..."
docker compose --profile "$PROFILE" exec "$SERVICE" \
  openclaw config set agents.defaults.model.primary "$MODEL"

echo "[2/6] Set workspace..."
docker compose --profile "$PROFILE" exec "$SERVICE" \
  openclaw config set agents.defaults.workspace "$WORKSPACE"

echo "[3/6] Apply restricted tool policy..."
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

echo "[4/6] Write SOUL.md + AGENTS.md..."
docker compose --profile "$PROFILE" exec -T "$SERVICE" \
  sh -lc "mkdir -p $WORKSPACE"
docker compose --profile "$PROFILE" exec -T "$SERVICE" \
  sh -lc "cat > $WORKSPACE/SOUL.md" < "$TMP_SOUL"
docker compose --profile "$PROFILE" exec -T "$SERVICE" \
  sh -lc "cat > $WORKSPACE/AGENTS.md" < "$TMP_AGENTS"

echo "[5/6] Restart service..."
docker compose --profile "$PROFILE" restart "$SERVICE"

echo "[6/6] Preview files..."
docker compose --profile "$PROFILE" exec "$SERVICE" sh -lc \
  "ls -la $WORKSPACE && echo '--- SOUL.md ---' && sed -n '1,120p' $WORKSPACE/SOUL.md && echo '--- AGENTS.md ---' && sed -n '1,180p' $WORKSPACE/AGENTS.md"

echo "Done."
echo "Tip: test with 'who are you?' after restart."
