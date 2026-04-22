import json
from typing import Any, Dict, List
from urllib.parse import urlparse

from .config import (
    LLM_DEFAULT_MODEL,
    LLM_MAX_CONTEXT_CONTENT_CHARS,
    LLM_MAX_CONTEXT_PAGES,
    LLM_MAX_CONTEXT_SUMMARY_CHARS,
    LLM_MAX_HISTORY_CHARS,
    LLM_MAX_HISTORY_MESSAGES,
    LLM_MAX_INPUT_TOKENS,
    LLM_MAX_SITE_CATALOG,
    LLM_MAX_TOOL_FIELDS,
    LLM_MAX_TOOL_MANIFESTS,
    LLM_MAX_TOOL_STEPS,
    SITE_NAVIGATION_BRIEF,
)
from .groq_client import post_chat_completion
from .knowledge_base import kb
from .nlp import OWNER_PROFILE
from .retrieval import url_path


def not_found_response(language: str) -> Dict[str, Any]:
    if language == "id":
        answer = (
            "Maaf, saya belum menemukan jawaban yang cukup relevan dari data website saat ini. "
            "Coba kirim pertanyaan yang lebih spesifik, misalnya tentang pricing, tools, artikel, atau kontak."
        )
    else:
        answer = (
            "Sorry, I could not find a sufficiently relevant answer from the current website data. "
            "Please ask with a more specific topic such as pricing, tools, articles, or contact."
        )
    return {"answer": answer, "recommended_type": "none", "recommended_url": "", "reason": "No match found.", "related_items": []}


def _truncate_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _approx_tokens(payload: Dict[str, Any]) -> int:
    serialized = json.dumps(payload, ensure_ascii=False)
    # Fast approximation: ~4 chars/token for mixed EN/ID text.
    return max(1, len(serialized) // 4)


def _compact_history(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    compact: List[Dict[str, str]] = []
    for item in history[-max(1, LLM_MAX_HISTORY_MESSAGES):]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        if role not in {"user", "assistant"}:
            continue
        content = _truncate_text(str(item.get("content", "")), max(120, LLM_MAX_HISTORY_CHARS))
        if not content:
            continue
        compact.append({"role": role, "content": content})
    return compact


def _compact_context_pages(context_pages: List[Dict[str, Any]], max_content_chars: int) -> List[Dict[str, str]]:
    compact: List[Dict[str, str]] = []
    for item in context_pages[: max(1, LLM_MAX_CONTEXT_PAGES)]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "title": _truncate_text(str(item.get("title", "")), 140),
                "url": str(item.get("url", "")).strip(),
                "summary": _truncate_text(str(item.get("summary", "")), max(80, LLM_MAX_CONTEXT_SUMMARY_CHARS)),
                "content": _truncate_text(str(item.get("content", "")), max(220, max_content_chars)),
                "source": _truncate_text(str(item.get("source", "")), 30),
            }
        )
    return compact


def _compact_site_catalog(site_catalog: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    compact: List[Dict[str, str]] = []
    for item in site_catalog[: max(1, LLM_MAX_SITE_CATALOG)]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "path": _truncate_text(str(item.get("path", "")), 90),
                "url": str(item.get("url", "")).strip(),
                "title": _truncate_text(str(item.get("title", "")), 90),
                "section": _truncate_text(str(item.get("section", "")), 40),
            }
        )
    return compact


def _compact_tool_manifests(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in items[: max(1, LLM_MAX_TOOL_MANIFESTS)]:
        if not isinstance(item, dict):
            continue
        raw_schema = item.get("input_schema", {})
        raw_fields = raw_schema.get("fields", []) if isinstance(raw_schema, dict) else []
        fields: List[Dict[str, Any]] = []
        for field in raw_fields[: max(1, LLM_MAX_TOOL_FIELDS)]:
            if not isinstance(field, dict):
                continue
            fields.append(
                {
                    "key": _truncate_text(str(field.get("key", "")), 48),
                    "label": _truncate_text(str(field.get("label", "")), 70),
                    "type": _truncate_text(str(field.get("type", "text")), 24),
                    "required": bool(field.get("required", False)),
                    "placeholder": _truncate_text(str(field.get("placeholder", "")), 80),
                    "hint": _truncate_text(str(field.get("hint", "")), 120),
                }
            )

        steps = item.get("steps", [])
        steps = [_truncate_text(str(step), 160) for step in steps[: max(1, LLM_MAX_TOOL_STEPS)] if str(step).strip()] if isinstance(steps, list) else []
        compact.append(
            {
                "slug": _truncate_text(str(item.get("slug", "")), 80),
                "name": _truncate_text(str(item.get("name", "")), 100),
                "url": str(item.get("url", "")).strip(),
                "description": _truncate_text(str(item.get("description", "")), 240),
                "input_schema": {"fields": fields},
                "steps": steps,
                "output_explained": _truncate_text(str(item.get("output_explained", "")), 260),
                "playbook": {
                    "what_it_does": _truncate_text(str((item.get("playbook", {}) or {}).get("what_it_does", "")), 260),
                    "input_tips": [
                        _truncate_text(str(v), 120)
                        for v in (((item.get("playbook", {}) or {}).get("input_tips", []) or [])[:6])
                        if str(v).strip()
                    ],
                    "troubleshooting": [
                        _truncate_text(str(v), 120)
                        for v in (((item.get("playbook", {}) or {}).get("troubleshooting", []) or [])[:5])
                        if str(v).strip()
                    ],
                },
                "hook": {
                    "examples": [
                        {
                            "label": _truncate_text(str((example or {}).get("label", "")), 60),
                            "value": _truncate_text(str((example or {}).get("value", "")), 120),
                        }
                        for example in (((item.get("hook", {}) or {}).get("examples", []) or [])[:6])
                        if isinstance(example, dict)
                    ],
                    "tips": [
                        _truncate_text(str(v), 120)
                        for v in (((item.get("hook", {}) or {}).get("tips", []) or [])[:6])
                        if str(v).strip()
                    ],
                },
            }
        )
    return compact


def _build_navigation_user_payload(
    *,
    message: str,
    history: List[Dict[str, Any]],
    context_pages: List[Dict[str, Any]],
    site_catalog: List[Dict[str, Any]],
    tool_manifest_context: List[Dict[str, Any]],
    tutorial_mode: bool,
    intent_mode: str,
    channel: str,
    prompt_variant: str,
) -> Dict[str, Any]:
    return {
        "question": _truncate_text(message, 900),
        "history": history,
        "page_context": context_pages,
        "site_catalog": site_catalog,
        "tool_manifest_context": tool_manifest_context,
        "tutorial_mode": tutorial_mode,
        "intent_mode": intent_mode,
        "channel": channel,
        "prompt_variant": prompt_variant,
    }


async def ask_groq_owner(message: str, history: List[Dict[str, Any]], language: str) -> Dict[str, Any]:
    system_prompt = f"""
You are Xiao-An, Aryakun's AI assistant.
Reply in {"Indonesian" if language == "id" else "English"}.
You are answering an owner/about query.
Facts: Name={OWNER_PROFILE["name"]}, Role={OWNER_PROFILE["role"]}, Traits={", ".join(OWNER_PROFILE["traits"])}.
Keep it factual and concise (1-3 sentences), focused on owner profile and website purpose.
Return valid JSON only: {{"answer":"string","recommended_type":"none","recommended_url":"","reason":"string","related_items":[]}}
""".strip()

    response_json, model_used = await post_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"question": message}, ensure_ascii=False)},
        ],
        temperature=0.65,
        response_format={"type": "json_object"},
        preferred_model=LLM_DEFAULT_MODEL,
    )

    try:
        result = json.loads(response_json["choices"][0]["message"]["content"])
        return {
            "answer": str(result.get("answer", "")),
            "recommended_type": "none",
            "recommended_url": "",
            "reason": f"User asked about owner. model={model_used}",
            "related_items": [],
        }
    except Exception:
        lang_answer = (
            "Aryakun adalah personal portfolio milik Arya. Website ini memperkenalkan owner, layanan, tools, dan konten terkait."
            if language == "id"
            else "Aryakun is Arya's personal portfolio website, introducing the owner profile, services, tools, and related content."
        )
        return {"answer": lang_answer, "recommended_type": "page", "recommended_url": "/about", "reason": "", "related_items": []}


async def ask_groq_navigate(
    message: str,
    history: List[Dict[str, Any]],
    context_pages: List[Dict[str, Any]],
    site_catalog: List[Dict[str, Any]],
    language: str,
    tutorial_mode: bool = False,
    tool_manifest_context: List[Dict[str, Any]] | None = None,
    intent_mode: str = "navigation",
    channel: str = "web",
    prompt_variant: str = "control",
    model_override: str = "",
) -> Dict[str, Any]:
    lang_name = "Indonesian" if language == "id" else "English"
    compact_history = _compact_history(history)
    compact_context = _compact_context_pages(context_pages, LLM_MAX_CONTEXT_CONTENT_CHARS)
    compact_catalog = _compact_site_catalog(site_catalog)
    compact_manifests = _compact_tool_manifests(tool_manifest_context or [])

    valid_urls: List[str] = []
    for item in compact_context:
        raw_url = str(item.get("url", "")).strip()
        if raw_url:
            valid_urls.append(raw_url)
    for item in compact_catalog:
        raw_url = str(item.get("url", "")).strip()
        if raw_url:
            valid_urls.append(raw_url)
    valid_urls = list(dict.fromkeys(valid_urls))

    tutorial_rules = """
TUTORIAL MODE:
- User asks how to use a tool. Prioritize tool_manifest_context as source-of-truth.
- Output answer in this structure:
  1) What the tool does
  2) Step-by-step usage
  3) Input field tips
  4) Output explanation
  5) Troubleshooting
- If manifest data is incomplete, explicitly say details are incomplete and do not guess.
""" if tutorial_mode else ""

    intent_rules = f"""
INTENT MODE:
- Active intent: {intent_mode}
- If intent is pricing: prioritize pricing/plan/cost pages.
- If intent is contact: prioritize contact/support channels.
- If intent is troubleshoot: answer with troubleshooting steps first.
- If intent is faq/navigation: prioritize concise factual direction.
""".strip()

    channel_rules = """
CHANNEL RULES:
- If channel=openclaw: keep answer compact for mobile chat, max 3 short paragraphs.
- If channel=openai: keep technical JSON-clean style and avoid decorative filler.
- If channel=web: balanced detail with clear link guidance.
""".strip()

    variant_rules = """
PROMPT VARIANT:
- control: balanced answer and navigation.
- concise: fewer words, direct instruction, one primary link only.
- advisor: include one short recommendation sentence before directing.
""".strip()

    system_prompt = f"""
You are Xiao-An, Aryakun's AI assistant.
Reply in {lang_name}. Match the user's language naturally.

SITE BRIEF:
- {SITE_NAVIGATION_BRIEF}
- Prioritize grounded answers from provided context and site_catalog.

PERSONALITY:
- Professional, friendly, and concise.
- Sound natural and helpful, not theatrical or roleplay-heavy.
- You are an assistant talking with clients. Never claim you are "the website".
- If user asks who you are, introduce yourself as Xiao-An, AI assistant of AryaKun.
- If relevant page found: mention WHY it fits in 1 sentence, then direct there.
- If no exact match: answer helpfully without forcing a link.
- Keep answer concise: 1-4 sentences max.

NAVIGATION RULES (CRITICAL):
1. Read ALL page_context entries carefully — these are the REAL contents of the website pages.
2. Use site_catalog to understand available pages/routes in the website.
3. If a page's content answers the user's question → direct user there AND briefly explain what they'll find.
4. If context is partial but site_catalog clearly has matching route (e.g., tools/pricing/blog/contact), you may direct to that route.
5. recommended_url MUST be taken from URLs available in page_context/site_catalog.
6. NEVER invent a URL. If nothing relevant → recommended_url = ""
7. Use page content to give a smart, specific answer — not a generic one.
8. Only return recommended_url when it is clearly relevant to the user's question.
9. For generic conversation/chitchat/non-website questions, set recommended_url = "".
10. If context is uncertain or weak, do not force links; ask a brief clarification instead.

RESPONSE STYLE:
- Answer as Xiao-An talking to a client.
- Keep concise.
- If no exact website grounding exists, answer helpfully without forcing a link.
- You are customer-service only: never claim you executed tools, changed account state, processed payment, or completed technical actions.
- If user asks execution, explicitly say you cannot execute and switch to guidance/tutorial mode.
{intent_rules}
{channel_rules}
{variant_rules}
Current channel={channel}, variant={prompt_variant}.
{tutorial_rules}

RESPONSE — valid JSON only, no markdown:
{{
  "answer": "string",
  "recommended_type": "tool|product|blog|page|none",
  "recommended_url": "string",
  "reason": "string",
  "related_items": [{{"title": "string", "type": "string", "url": "string"}}]
}}
""".strip()

    def _make_payload() -> Dict[str, Any]:
        user_payload = _build_navigation_user_payload(
            message=message,
            history=compact_history,
            context_pages=compact_context,
            site_catalog=compact_catalog,
            tool_manifest_context=compact_manifests,
            tutorial_mode=tutorial_mode,
            intent_mode=intent_mode,
            channel=channel,
            prompt_variant=prompt_variant,
        )
        return {
            "model": model_override.strip() or LLM_DEFAULT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

    payload = _make_payload()

    # Keep request safely under provider TPM/token window by shrinking context progressively.
    max_input_tokens = max(800, LLM_MAX_INPUT_TOKENS)
    reductions = 0
    while _approx_tokens(payload) > max_input_tokens and reductions < 12:
        reductions += 1
        if len(compact_catalog) > 12:
            compact_catalog = compact_catalog[:-4]
        elif len(compact_context) > 2:
            compact_context = compact_context[:-1]
        elif len(compact_manifests) > 1:
            compact_manifests = compact_manifests[:1]
        elif len(compact_history) > 1:
            compact_history = compact_history[1:]
        else:
            shrunk_context = _compact_context_pages(compact_context, max(220, LLM_MAX_CONTEXT_CONTENT_CHARS // 2))
            if shrunk_context != compact_context:
                compact_context = shrunk_context
            else:
                break
        payload = _make_payload()

    response_json, model_used = await post_chat_completion(
        messages=payload["messages"],
        temperature=payload["temperature"],
        response_format=payload["response_format"],
        preferred_model=model_override.strip() or LLM_DEFAULT_MODEL,
    )

    try:
        result = json.loads(response_json["choices"][0]["message"]["content"])
    except Exception:
        return not_found_response(language)

    rec_url = str(result.get("recommended_url", "")).strip()
    if rec_url and rec_url not in valid_urls:
        rec_path = rec_url if not rec_url.startswith("http") else urlparse(rec_url).path
        if rec_path.rstrip("/") not in kb.get_paths():
            result["recommended_url"] = ""
            result["recommended_type"] = "none"

    all_paths = kb.get_paths()
    result["related_items"] = [
        item
        for item in result.get("related_items", [])
        if url_path(str(item.get("url", ""))) in all_paths or str(item.get("url", "")) in valid_urls
    ]

    if not result.get("answer"):
        return not_found_response(language)
    result["reason"] = (
        str(result.get("reason", "")).strip()
        + f" model={model_used} variant={prompt_variant} intent={intent_mode} channel={channel}"
    ).strip()
    return result
