import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import (
    CONTEXT_MAX_PAGES,
    GROQ_API_KEY,
    OPENAI_HISTORY_LIMIT,
    OPENAI_MESSAGE_MAX_CHARS,
    OPENCLAW_COMPAT_API_KEY,
    OPENCLAW_COMPAT_MODEL_ID,
    SITE_CATALOG_MAX_ITEMS,
)
from .knowledge_base import kb
from .llm import ask_groq_navigate, ask_groq_owner, not_found_response
from .nlp import (
    detect_language,
    build_search_queries,
    identity_response,
    is_identity_query,
    is_owner_query,
    is_tutorial_intent,
)
from .retrieval import build_context_for_groq, enrich_navigation_result, merge_search_items, search_website
from .tools_manifest import find_relevant_tool_manifests


logger = logging.getLogger("ai_fastapi")


def _manifest_to_context_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    fields = []
    input_schema = item.get("input_schema", {})
    if isinstance(input_schema, dict):
        fields = input_schema.get("fields", [])
        fields = fields if isinstance(fields, list) else []

    field_lines: List[str] = []
    for field in fields[:12]:
        if not isinstance(field, dict):
            continue
        key = str(field.get("key", "")).strip()
        label = str(field.get("label", "")).strip() or key
        field_type = str(field.get("type", "text")).strip() or "text"
        required = bool(field.get("required", False))
        hint = str(field.get("hint", "")).strip()
        line = f"{label} [{field_type}]"
        if required:
            line += " required"
        if hint:
            line += f" — {hint}"
        field_lines.append(line)

    steps = item.get("steps", [])
    steps = [str(v).strip() for v in steps if str(v).strip()] if isinstance(steps, list) else []
    output = str(item.get("output_explained", "")).strip()

    content_parts: List[str] = []
    if field_lines:
        content_parts.append("Input fields:\n- " + "\n- ".join(field_lines[:10]))
    if steps:
        content_parts.append("Usage steps:\n- " + "\n- ".join(steps[:8]))
    if output:
        content_parts.append("Output explained: " + output)

    return {
        "title": str(item.get("name", "")).strip() or str(item.get("slug", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "summary": str(item.get("description", "")).strip(),
        "content": "\n\n".join(content_parts).strip(),
        "source": "tool-manifest",
    }


def _merge_context_with_priority(
    primary: List[Dict[str, Any]],
    secondary: List[Dict[str, Any]],
    max_items: int,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for item in primary + secondary:
        if not isinstance(item, dict):
            continue
        key = f"{str(item.get('url', '')).strip()}|{str(item.get('title', '')).strip()}|{str(item.get('source', '')).strip()}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= max_items:
            break

    return merged


def _format_tutorial_fallback(manifest: Dict[str, Any], language: str) -> str:
    name = str(manifest.get("name", "this tool")).strip() or "this tool"
    desc = str(manifest.get("description", "")).strip()
    steps = manifest.get("steps", [])
    steps = [str(v).strip() for v in steps if str(v).strip()] if isinstance(steps, list) else []
    output = str(manifest.get("output_explained", "")).strip()
    input_schema = manifest.get("input_schema", {})
    fields = input_schema.get("fields", []) if isinstance(input_schema, dict) else []
    field_lines = []
    for field in fields[:8]:
        if not isinstance(field, dict):
            continue
        label = str(field.get("label", "")).strip() or str(field.get("key", "")).strip()
        ftype = str(field.get("type", "text")).strip() or "text"
        req = "required" if bool(field.get("required", False)) else "optional"
        field_lines.append(f"- {label} [{ftype}] ({req})")

    if language == "id":
        parts = [f"Aiya gege, ini cara pakai {name} ya."]
        if desc:
            parts.append("Fungsi: " + desc)
        if steps:
            parts.append("Langkah:\n" + "\n".join(f"{i+1}. {v}" for i, v in enumerate(steps[:6])))
        if field_lines:
            parts.append("Input penting:\n" + "\n".join(field_lines))
        if output:
            parts.append("Output: " + output)
        parts.append("Kalau ada field/tool detail yang belum jelas, Xiao-An kasih versi dasar dulu dari data yang tersedia.")
        return "\n\n".join(parts)

    parts = [f"Aiya gege, here is how to use {name}."]
    if desc:
        parts.append("What it does: " + desc)
    if steps:
        parts.append("Steps:\n" + "\n".join(f"{i+1}. {v}" for i, v in enumerate(steps[:6])))
    if field_lines:
        parts.append("Important inputs:\n" + "\n".join(field_lines))
    if output:
        parts.append("Output: " + output)
    parts.append("If some details are missing, Xiao-An is using the best available tool manifest data.")
    return "\n\n".join(parts)


def _answer_has_tutorial_shape(answer: str, language: str) -> bool:
    text = answer.lower()
    markers = ["langkah", "steps", "input", "output", "troubleshooting", "cara pakai", "how to use"]
    return sum(1 for m in markers if m in text) >= 2


def format_ai_result_text(result: Dict[str, Any], language: str) -> str:
    answer = str(result.get("answer", "")).strip()
    rec_url = str(result.get("recommended_url", "")).strip()
    related = result.get("related_items", [])
    related = related if isinstance(related, list) else []

    lines: List[str] = [answer] if answer else []

    if rec_url:
        label = "Link relevan" if language == "id" else "Relevant link"
        lines.append(f"{label}: {rec_url}")

    compact_related: List[str] = []
    for item in related[:2]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        compact_related.append(f"- {title}: {url}" if title else f"- {url}")

    if compact_related:
        label = "Link terkait" if language == "id" else "Related links"
        lines.append(label + ":\n" + "\n".join(compact_related))

    return "\n\n".join(line for line in lines if line.strip())


def present_ai_result(result: Dict[str, Any], language: str) -> Dict[str, Any]:
    payload = dict(result)
    raw_answer = str(payload.get("answer", "")).strip()
    rendered_answer = format_ai_result_text(payload, language).strip()

    payload["answer_raw"] = raw_answer
    payload["answer"] = rendered_answer or raw_answer
    return payload


async def generate_chat_response(message: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is not configured")

    language = detect_language(message, history)

    if kb.page_count == 0:
        try:
            await kb.force_crawl()
        except Exception:
            pass

    if kb.is_stale:
        asyncio.create_task(kb.crawl())

    if is_owner_query(message):
        try:
            return await ask_groq_owner(message, history, language)
        except Exception:
            return not_found_response(language)

    if is_identity_query(message):
        return identity_response(language)

    tutorial_mode = is_tutorial_intent(message)
    tool_manifests: List[Dict[str, Any]] = []
    tool_context: List[Dict[str, Any]] = []
    if tutorial_mode:
        try:
            tool_manifests = await find_relevant_tool_manifests(message, top_k=3)
            tool_context = [_manifest_to_context_entry(item) for item in tool_manifests]
        except Exception:
            tool_manifests = []
            tool_context = []

    search_queries = build_search_queries(message, history)
    search_batches = await asyncio.gather(*(search_website(q) for q in search_queries[:3]))
    search_items = merge_search_items(search_batches)
    base_context = build_context_for_groq(search_queries[0], search_items)
    context_pages = _merge_context_with_priority(tool_context, base_context, max_items=CONTEXT_MAX_PAGES)

    site_catalog = kb.get_catalog(max_items=min(SITE_CATALOG_MAX_ITEMS, 40))
    for item in tool_manifests[:20]:
        site_catalog.append(
            {
                "path": str(item.get("slug", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "title": str(item.get("name", "")).strip(),
                "section": "tools",
            }
        )

    try:
        result = await ask_groq_navigate(
            message,
            history,
            context_pages,
            site_catalog,
            language,
            tutorial_mode=tutorial_mode,
            tool_manifest_context=tool_manifests,
        )
        result = enrich_navigation_result(result, context_pages, message)

        if tutorial_mode and tool_manifests:
            primary = tool_manifests[0]
            primary_url = str(primary.get("url", "")).strip()
            if primary_url and not str(result.get("recommended_url", "")).strip():
                result["recommended_url"] = primary_url
                result["recommended_type"] = "tool"

            answer = str(result.get("answer", "")).strip()
            if not _answer_has_tutorial_shape(answer, language):
                result["answer"] = _format_tutorial_fallback(primary, language)
                result["reason"] = (str(result.get("reason", "")).strip() + " Tutorial template fallback from tool manifest.").strip()

        return result
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        logger.error("Groq HTTP error: %s", detail)
        fallback = not_found_response(language)
        fallback = enrich_navigation_result(fallback, context_pages, message)
        fallback["reason"] = f"Groq error fallback: {detail[:300]}"
        if tutorial_mode and tool_manifests:
            primary = tool_manifests[0]
            fallback["answer"] = _format_tutorial_fallback(primary, language)
            fallback["recommended_url"] = str(primary.get("url", "")).strip()
            fallback["recommended_type"] = "tool" if fallback["recommended_url"] else fallback.get("recommended_type", "none")
        return fallback
    except Exception as e:
        logger.exception("Unexpected AI error")
        fallback = not_found_response(language)
        fallback = enrich_navigation_result(fallback, context_pages, message)
        fallback["reason"] = f"AI error fallback: {str(e)[:300]}"
        if tutorial_mode and tool_manifests:
            primary = tool_manifests[0]
            fallback["answer"] = _format_tutorial_fallback(primary, language)
            fallback["recommended_url"] = str(primary.get("url", "")).strip()
            fallback["recommended_type"] = "tool" if fallback["recommended_url"] else fallback.get("recommended_type", "none")
        return fallback


def _get_nested(payload: Dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part, "")
    return current


def _extract_first_non_empty(payload: Dict[str, Any], candidates: List[str]) -> str:
    for path in candidates:
        value = str(_get_nested(payload, path)).strip()
        if value:
            return value
    return ""


def extract_openclaw_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    message = _extract_first_non_empty(
        payload,
        ["message", "text", "content", "data.message", "data.text", "event.message.text", "event.text"],
    )
    user_id = _extract_first_non_empty(
        payload,
        [
            "user_id",
            "sender_id",
            "from",
            "user.id",
            "sender.id",
            "data.user_id",
            "data.sender_id",
            "data.user.id",
            "data.sender.id",
        ],
    )

    source_history = payload.get("history", payload.get("messages", []))
    history: List[Dict[str, str]] = []
    if isinstance(source_history, list):
        for item in source_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", item.get("text", ""))).strip()
            if role in {"user", "assistant"} and content:
                history.append({"role": role, "content": content})

    return {"message": message, "history": history, "user_id": user_id or None}


def require_bearer_auth_if_configured(request: Request):
    if not OPENCLAW_COMPAT_API_KEY:
        return
    auth = request.headers.get("authorization", "").strip()
    expected = f"Bearer {OPENCLAW_COMPAT_API_KEY}"
    if auth != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()[:OPENAI_MESSAGE_MAX_CHARS]

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append(text)
                continue

            if not isinstance(item, dict):
                continue

            if item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
        return " ".join(parts).strip()[:OPENAI_MESSAGE_MAX_CHARS]

    return ""


def openai_messages_to_internal(messages: Any) -> Dict[str, Any]:
    if not isinstance(messages, list):
        return {"message": "", "history": []}

    parsed: List[Dict[str, str]] = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role", "")).strip()
        if role not in {"user", "assistant"}:
            continue
        content = _content_to_text(raw.get("content", ""))
        if not content:
            continue
        parsed.append({"role": role, "content": content})

    if not parsed:
        return {"message": "", "history": []}

    last_user_index = -1
    for i in range(len(parsed) - 1, -1, -1):
        if parsed[i]["role"] == "user":
            last_user_index = i
            break

    if last_user_index < 0:
        return {"message": "", "history": parsed[-6:]}

    message = parsed[last_user_index]["content"]
    history = parsed[:last_user_index][-OPENAI_HISTORY_LIMIT:]
    return {"message": message, "history": history}


def build_models_response() -> Dict[str, Any]:
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": OPENCLAW_COMPAT_MODEL_ID,
                "object": "model",
                "created": now,
                "owned_by": "ai_fastapi",
            }
        ],
    }


async def build_openai_chat_completion(payload: Dict[str, Any]) -> Any:
    model = str(payload.get("model") or OPENCLAW_COMPAT_MODEL_ID)
    stream = bool(payload.get("stream", False))

    parsed = openai_messages_to_internal(payload.get("messages", []))
    message = str(parsed.get("message", "")).strip()
    history = parsed.get("history", [])

    if not message:
        raise HTTPException(status_code=422, detail="Invalid payload: user message is required")

    ai_result = await generate_chat_response(message, history)
    language = detect_language(message, history)
    presented = present_ai_result(ai_result, language)
    answer = str(presented.get("answer", "")).strip()

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if stream:
        async def event_stream():
            first_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": answer}, "finish_reason": None}],
            }
            end_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }

            yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps(end_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
