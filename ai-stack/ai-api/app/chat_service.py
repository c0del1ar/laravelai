import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .channel_policy import apply_channel_guardrails
from .config import (
    APP_LOG_LEVEL,
    CS_ONLY_MODE,
    CONTEXT_MAX_PAGES,
    GROQ_API_KEY,
    HUMAN_HANDOFF_CONTACT_URL,
    HUMAN_HANDOFF_ENABLED,
    LOW_CONFIDENCE_THRESHOLD,
    OPENAI_HISTORY_LIMIT,
    OPENAI_MESSAGE_MAX_CHARS,
    OPENCLAW_COMPAT_API_KEY,
    OPENCLAW_COMPAT_MODEL_ID,
    OPENCLAW_PREFIX_GATE_ENABLED,
    OPENCLAW_PREFIX_GATE_HARD_IGNORE,
    OPENCLAW_PREFIX_REMINDER_TEXT,
    OPENCLAW_PREFIX_REMINDER_TEXT_EN,
    OPENCLAW_REQUIRED_PREFIX,
    SITE_CATALOG_MAX_ITEMS,
    STRICT_GROUNDING_ENABLED,
    STRICT_GROUNDING_MIN_CONFIDENCE,
    STRICT_GROUNDING_REQUIRE_SOURCE,
)
from .experiments import choose_experiment_variant
from .handoff_state import handoff_state
from .intent_router import classify_intent_profile, expand_queries_for_intent
from .knowledge_base import kb
from .learning_loop import learning_store
from .llm import ask_groq_navigate, ask_groq_owner, not_found_response
from .memory_store import memory_store
from .nlp import (
    detect_language,
    identity_response,
    is_identity_query,
    is_owner_query,
    is_smalltalk_intent,
    should_handoff_to_human,
)
from .retrieval import (
    build_context_for_groq,
    build_response_sources,
    enrich_navigation_result,
    estimate_confidence,
    has_context_relevance,
    merge_search_items,
    search_website,
)
from .observability import observability
from .prefix_gate_store import prefix_gate_store
from .response_cache import build_response_cache_key, response_cache
from .site_catalog import build_catalog_context_entries, fetch_site_catalog, merge_site_catalogs, rank_catalog_items
from .tool_hooks import apply_tool_hook
from .tools_manifest import fetch_tool_manifest_by_slug, find_relevant_tool_manifests


logger = logging.getLogger("ai_fastapi")
_LOG_LEVEL = getattr(logging, APP_LOG_LEVEL, logging.INFO)
logger.setLevel(_LOG_LEVEL)
_PHONE_TOKEN_RE = re.compile(r"(\+?\d{9,16})")


def _clarification_answer(language: str) -> str:
    if language == "id":
        return (
            "Aiya gege, Xiao-An butuh detail dikit biar jawabannya tepat ya. "
            "Kamu lagi cari info fitur, pricing, artikel, atau panduan pakai tool tertentu?"
        )
    return (
        "Aiya gege, Xiao-An needs a bit more detail so the answer is accurate. "
        "Are you looking for features, pricing, article, or a specific tool tutorial?"
    )


def _smalltalk_answer(language: str) -> str:
    if language == "id":
        return (
            "Aiya gege, Xiao-An di sini kok. Kalau mau, kasih topik website AryaKun yang mau kamu cari "
            "seperti pricing, tools, fitur, atau kontak, nanti Xiao-An bantu cepat ya."
        )
    return (
        "Aiya gege, Xiao-An is here. If you want, tell me what you need from AryaKun website "
        "like pricing, tools, features, or contact, and I will guide you quickly."
    )


def _human_handoff_answer(language: str) -> str:
    contact_url = str(HUMAN_HANDOFF_CONTACT_URL or "").strip()
    if contact_url and not contact_url.startswith("http"):
        if not contact_url.startswith("/"):
            contact_url = "/" + contact_url
    if language == "id":
        if contact_url:
            return (
                "Aiya gege, biar lebih cepat Xiao-An sambungkan ke tim manusia dulu ya. "
                f"Kamu bisa lanjut lewat {contact_url}."
            )
        return "Aiya gege, biar lebih cepat Xiao-An sambungkan ke tim manusia dulu ya."
    if contact_url:
        return (
            "Aiya gege, for this case Xiao-An will route you to the human team for faster help. "
            f"Please continue via {contact_url}."
        )
    return "Aiya gege, for this case Xiao-An will route you to the human team for faster help."


def _cs_execution_block_intro(language: str, target: str) -> str:
    if language == "id":
        if target == "account":
            return (
                "Aiya gege, Xiao-An mode customer service ya, jadi tidak bisa mengubah akun/transaksi langsung. "
                "Xiao-An bisa bantu arahkan langkah aman atau sambungkan ke tim manusia."
            )
        return (
            "Aiya gege, Xiao-An mode customer service ya, jadi tidak bisa mengeksekusi tool atau aksi otomatis secara langsung. "
            "Xiao-An bisa kasih panduan step-by-step sampai kamu bisa jalanin sendiri."
        )
    if target == "account":
        return (
            "Aiya gege, Xiao-An is in customer-service mode, so I cannot directly change account or transaction data. "
            "I can guide safe steps or route you to the human team."
        )
    return (
        "Aiya gege, Xiao-An is in customer-service mode, so I cannot directly execute tools or automated actions. "
        "I can provide step-by-step guidance so you can run it yourself."
    )


def _is_grounded_enough(result: Dict[str, Any], context_pages: List[Dict[str, Any]], message: str) -> bool:
    confidence = float(result.get("confidence_score", 0.0) or 0.0)
    if confidence < STRICT_GROUNDING_MIN_CONFIDENCE:
        return False
    if not STRICT_GROUNDING_REQUIRE_SOURCE:
        return True
    if has_context_relevance(message, context_pages):
        return True
    rec_url = str(result.get("recommended_url", "")).strip()
    if rec_url:
        known_urls = {
            str(item.get("url", "")).strip()
            for item in context_pages
            if isinstance(item, dict) and str(item.get("url", "")).strip()
        }
        if rec_url in known_urls:
            return True
    return False


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
    playbook = item.get("playbook", {})
    playbook = playbook if isinstance(playbook, dict) else {}
    pb_what = str(playbook.get("what_it_does", "")).strip()
    pb_tips = [str(v).strip() for v in playbook.get("input_tips", []) if str(v).strip()] if isinstance(playbook.get("input_tips", []), list) else []
    pb_troubleshoot = [str(v).strip() for v in playbook.get("troubleshooting", []) if str(v).strip()] if isinstance(playbook.get("troubleshooting", []), list) else []
    hook = item.get("hook", {})
    hook = hook if isinstance(hook, dict) else {}
    hook_examples = hook.get("examples", [])
    hook_examples = hook_examples if isinstance(hook_examples, list) else []
    hook_tips = [str(v).strip() for v in hook.get("tips", []) if str(v).strip()] if isinstance(hook.get("tips", []), list) else []

    content_parts: List[str] = []
    if pb_what:
        content_parts.append("What it does: " + pb_what)
    if field_lines:
        content_parts.append("Input fields:\n- " + "\n- ".join(field_lines[:10]))
    if steps:
        content_parts.append("Usage steps:\n- " + "\n- ".join(steps[:8]))
    if pb_tips:
        content_parts.append("Input tips:\n- " + "\n- ".join(pb_tips[:8]))
    if output:
        content_parts.append("Output explained: " + output)
    if pb_troubleshoot:
        content_parts.append("Troubleshooting:\n- " + "\n- ".join(pb_troubleshoot[:6]))
    if hook_tips:
        content_parts.append("Hook tips:\n- " + "\n- ".join(hook_tips[:6]))
    if hook_examples:
        lines = []
        for example in hook_examples[:5]:
            if not isinstance(example, dict):
                continue
            label = str(example.get("label", "")).strip()
            value = str(example.get("value", "")).strip()
            if label or value:
                lines.append(f"{label}: {value}".strip(": "))
        if lines:
            content_parts.append("Example inputs:\n- " + "\n- ".join(lines))

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
    playbook = manifest.get("playbook", {})
    playbook = playbook if isinstance(playbook, dict) else {}
    pb_what = str(playbook.get("what_it_does", "")).strip()
    pb_tips = [str(v).strip() for v in playbook.get("input_tips", []) if str(v).strip()] if isinstance(playbook.get("input_tips", []), list) else []
    pb_troubleshoot = [str(v).strip() for v in playbook.get("troubleshooting", []) if str(v).strip()] if isinstance(playbook.get("troubleshooting", []), list) else []
    hook = manifest.get("hook", {})
    hook = hook if isinstance(hook, dict) else {}
    hook_tips = [str(v).strip() for v in hook.get("tips", []) if str(v).strip()] if isinstance(hook.get("tips", []), list) else []
    hook_examples = hook.get("examples", [])
    hook_examples = hook_examples if isinstance(hook_examples, list) else []
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
        if pb_what:
            parts.append("Fungsi: " + pb_what)
        elif desc:
            parts.append("Fungsi: " + desc)
        if steps:
            parts.append("Langkah:\n" + "\n".join(f"{i+1}. {v}" for i, v in enumerate(steps[:6])))
        if field_lines:
            parts.append("Input penting:\n" + "\n".join(field_lines))
        if pb_tips:
            parts.append("Tips input:\n" + "\n".join(f"- {v}" for v in pb_tips[:6]))
        if hook_tips:
            parts.append("Tips lanjutan:\n" + "\n".join(f"- {v}" for v in hook_tips[:5]))
        if hook_examples:
            sample = []
            for example in hook_examples[:4]:
                if not isinstance(example, dict):
                    continue
                label = str(example.get("label", "")).strip()
                value = str(example.get("value", "")).strip()
                if label or value:
                    sample.append(f"- {label}: {value}".strip(": "))
            if sample:
                parts.append("Contoh input:\n" + "\n".join(sample))
        if output:
            parts.append("Output: " + output)
        if pb_troubleshoot:
            parts.append("Troubleshooting:\n" + "\n".join(f"- {v}" for v in pb_troubleshoot[:5]))
        parts.append("Kalau ada field/tool detail yang belum jelas, Xiao-An kasih versi dasar dulu dari data yang tersedia.")
        return "\n\n".join(parts)

    parts = [f"Aiya gege, here is how to use {name}."]
    if pb_what:
        parts.append("What it does: " + pb_what)
    elif desc:
        parts.append("What it does: " + desc)
    if steps:
        parts.append("Steps:\n" + "\n".join(f"{i+1}. {v}" for i, v in enumerate(steps[:6])))
    if field_lines:
        parts.append("Important inputs:\n" + "\n".join(field_lines))
    if pb_tips:
        parts.append("Input tips:\n" + "\n".join(f"- {v}" for v in pb_tips[:6]))
    if hook_tips:
        parts.append("Extra tips:\n" + "\n".join(f"- {v}" for v in hook_tips[:5]))
    if hook_examples:
        sample = []
        for example in hook_examples[:4]:
            if not isinstance(example, dict):
                continue
            label = str(example.get("label", "")).strip()
            value = str(example.get("value", "")).strip()
            if label or value:
                sample.append(f"- {label}: {value}".strip(": "))
        if sample:
            parts.append("Example inputs:\n" + "\n".join(sample))
    if output:
        parts.append("Output: " + output)
    if pb_troubleshoot:
        parts.append("Troubleshooting:\n" + "\n".join(f"- {v}" for v in pb_troubleshoot[:5]))
    parts.append("If some details are missing, Xiao-An is using the best available tool manifest data.")
    return "\n\n".join(parts)


def _answer_has_tutorial_shape(answer: str, language: str) -> bool:
    text = answer.lower()
    markers = ["langkah", "steps", "input", "output", "troubleshooting", "cara pakai", "how to use"]
    return sum(1 for m in markers if m in text) >= 2


def format_ai_result_text(result: Dict[str, Any], language: str, channel: str = "web") -> str:
    answer = str(result.get("answer", "")).strip()
    rec_url = str(result.get("recommended_url", "")).strip()
    related = result.get("related_items", [])
    related = related if isinstance(related, list) else []
    sources = result.get("sources", [])
    sources = sources if isinstance(sources, list) else []

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

    source_lines: List[str] = []
    for item in sources[:2]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        source_lines.append(f"- {title}: {url}" if title else f"- {url}")

    if source_lines and channel != "openclaw":
        label = "Sumber" if language == "id" else "Sources"
        lines.append(label + ":\n" + "\n".join(source_lines))

    return "\n\n".join(line for line in lines if line.strip())


def present_ai_result(result: Dict[str, Any], language: str, channel: str = "web") -> Dict[str, Any]:
    payload = dict(result)
    payload["response_id"] = str(payload.get("response_id", "")).strip() or f"res_{uuid.uuid4().hex[:16]}"
    raw_answer = str(payload.get("answer", "")).strip()
    rendered_answer = format_ai_result_text(payload, language, channel=channel).strip()

    payload["answer_raw"] = raw_answer
    payload["answer"] = rendered_answer or raw_answer
    payload["confidence_score"] = float(payload.get("confidence_score", 0.0) or 0.0)
    payload["sources"] = payload.get("sources", []) if isinstance(payload.get("sources", []), list) else []
    return payload


async def generate_chat_response(
    message: str,
    history: List[Dict[str, Any]],
    user_id: str | None = None,
    channel: str = "web",
) -> Dict[str, Any]:
    started_at = time.perf_counter()

    async def _record(
        success: bool,
        confidence: float,
        context_count: int,
        reason: str = "",
        intent: str = "",
        variant: str = "",
        low_confidence: bool = False,
        handoff: bool = False,
        cache_hit: bool = False,
        grounded: bool = True,
    ):
        await observability.record_chat(
            channel=channel,
            success=success,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            confidence=confidence,
            context_pages=context_count,
            reason=reason,
            intent_mode=intent,
            experiment_variant=variant,
            low_confidence=low_confidence,
            handoff=handoff,
            cache_hit=cache_hit,
            grounded=grounded,
        )

    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is not configured")

    merged_history = await memory_store.merge_with_request_history(user_id or "", channel, history)
    language = detect_language(message, merged_history)
    intent_profile = classify_intent_profile(message)
    intent_mode = str(intent_profile.get("intent_mode", "navigation"))
    tutorial_mode = bool(intent_profile.get("tutorial_mode", False))
    experiment_variant, experiment_model = choose_experiment_variant(user_id or "", channel)

    if kb.page_count == 0:
        try:
            await kb.force_crawl()
        except Exception:
            pass

    if kb.is_stale:
        asyncio.create_task(kb.crawl())

    if is_owner_query(message):
        try:
            result = await ask_groq_owner(message, merged_history, language)
            result["intent_mode"] = "owner"
            result = apply_channel_guardrails(result, channel)
            await memory_store.add_turn(user_id or "", channel, message, str(result.get("answer", "")))
            await _record(True, 0.92, 0, str(result.get("reason", "")), intent="owner")
            return result
        except Exception:
            fallback = not_found_response(language)
            fallback["intent_mode"] = "owner"
            fallback = apply_channel_guardrails(fallback, channel)
            await memory_store.add_turn(user_id or "", channel, message, str(fallback.get("answer", "")))
            await _record(False, 0.22, 0, "owner route fallback", intent="owner")
            return fallback

    if is_identity_query(message):
        result = identity_response(language)
        result["intent_mode"] = "identity"
        result = apply_channel_guardrails(result, channel)
        await memory_store.add_turn(user_id or "", channel, message, str(result.get("answer", "")))
        await _record(True, 0.9, 0, "identity", intent="identity")
        return result

    if HUMAN_HANDOFF_ENABLED and should_handoff_to_human(message):
        result = {
            "answer": _human_handoff_answer(language),
            "recommended_type": "page" if HUMAN_HANDOFF_CONTACT_URL else "none",
            "recommended_url": str(HUMAN_HANDOFF_CONTACT_URL or "").strip(),
            "reason": "explicit handoff request",
            "related_items": [],
            "sources": [],
            "confidence_score": 0.96,
            "intent_mode": "handoff",
            "experiment_variant": experiment_variant,
            "experiment_model": experiment_model,
        }
        result = apply_channel_guardrails(result, channel)
        await memory_store.add_turn(user_id or "", channel, message, str(result.get("answer", "")))
        await _record(True, 0.96, 0, "handoff keyword", intent="handoff", variant=experiment_variant, handoff=True)
        return result

    if CS_ONLY_MODE and bool(intent_profile.get("execution_request", False)):
        execution_target = str(intent_profile.get("execution_target", "general")).strip() or "general"
        intro = _cs_execution_block_intro(language, execution_target)
        block_result: Dict[str, Any] = {
            "answer": intro,
            "recommended_type": "none",
            "recommended_url": "",
            "reason": f"cs-only execution blocked ({execution_target})",
            "related_items": [],
            "sources": [],
            "confidence_score": 0.9,
            "intent_mode": "cs_blocked_execution",
            "experiment_variant": experiment_variant,
            "experiment_model": experiment_model,
        }

        if execution_target == "account" and HUMAN_HANDOFF_CONTACT_URL:
            block_result["recommended_type"] = "page"
            block_result["recommended_url"] = str(HUMAN_HANDOFF_CONTACT_URL or "").strip()
            block_result["answer"] = (intro + " " + _human_handoff_answer(language)).strip()

        if execution_target == "tool":
            manifests: List[Dict[str, Any]] = []
            try:
                tool_slug_hint = str(intent_profile.get("tool_slug_hint", "")).strip()
                if tool_slug_hint:
                    hinted = await fetch_tool_manifest_by_slug(tool_slug_hint)
                    if hinted:
                        manifests.append(apply_tool_hook(hinted))
                discovered = await find_relevant_tool_manifests(message, top_k=2)
                for item in discovered:
                    slug = str(item.get("slug", "")).strip().lower()
                    if slug and any(str(v.get("slug", "")).strip().lower() == slug for v in manifests):
                        continue
                    manifests.append(apply_tool_hook(item))
                manifests = manifests[:2]
            except Exception:
                manifests = []

            if manifests:
                primary = manifests[0]
                tutorial_text = _format_tutorial_fallback(primary, language)
                block_result["answer"] = (intro + "\n\n" + tutorial_text).strip()
                primary_url = str(primary.get("url", "")).strip()
                if primary_url:
                    block_result["recommended_type"] = "tool"
                    block_result["recommended_url"] = primary_url
                    block_result["sources"] = [
                        {
                            "title": str(primary.get("name", "")).strip() or primary_url,
                            "url": primary_url,
                            "source": "tool-manifest",
                            "snippet": str(primary.get("description", "")).strip()[:180],
                        }
                    ]

        block_result = apply_channel_guardrails(block_result, channel)
        await memory_store.add_turn(user_id or "", channel, message, str(block_result.get("answer", "")))
        await _record(
            True,
            float(block_result.get("confidence_score", 0.0) or 0.0),
            0,
            str(block_result.get("reason", "")),
            intent="cs_blocked_execution",
            variant=experiment_variant,
        )
        return block_result

    if is_smalltalk_intent(message):
        result = {
            "answer": _smalltalk_answer(language),
            "recommended_type": "none",
            "recommended_url": "",
            "reason": "smalltalk short-circuit",
            "related_items": [],
            "sources": [],
            "confidence_score": 0.86,
            "intent_mode": "smalltalk",
            "experiment_variant": experiment_variant,
        }
        result = apply_channel_guardrails(result, channel)
        await memory_store.add_turn(user_id or "", channel, message, str(result.get("answer", "")))
        await _record(True, 0.86, 0, "smalltalk", intent="smalltalk", variant=experiment_variant)
        return result

    tool_manifests: List[Dict[str, Any]] = []
    tool_context: List[Dict[str, Any]] = []
    if tutorial_mode:
        try:
            tool_slug_hint = str(intent_profile.get("tool_slug_hint", "")).strip()
            if tool_slug_hint:
                hinted = await fetch_tool_manifest_by_slug(tool_slug_hint)
                if hinted:
                    tool_manifests.append(hinted)
            discovered = await find_relevant_tool_manifests(message, top_k=3)
            for item in discovered:
                slug = str(item.get("slug", "")).strip().lower()
                if slug and any(str(v.get("slug", "")).strip().lower() == slug for v in tool_manifests):
                    continue
                tool_manifests.append(item)
            tool_manifests = tool_manifests[:4]
            tool_manifests = [apply_tool_hook(item) for item in tool_manifests]
            tool_context = [_manifest_to_context_entry(item) for item in tool_manifests]
        except Exception:
            tool_manifests = []
            tool_context = []

    search_queries = expand_queries_for_intent(message, merged_history, intent_profile)

    search_batches = await asyncio.gather(*(search_website(q) for q in search_queries[:3]))
    search_items = merge_search_items(search_batches)
    semantic_chunks = await kb.search_semantic_chunks(search_queries[0], top_k=8)
    local_catalog = kb.get_catalog(max_items=min(SITE_CATALOG_MAX_ITEMS, 120))
    remote_catalog = await fetch_site_catalog()
    merged_catalog = merge_site_catalogs(local_catalog, remote_catalog, max_items=min(SITE_CATALOG_MAX_ITEMS, 180))
    catalog_candidates = rank_catalog_items(
        search_queries[0],
        merged_catalog,
        intent_mode=intent_mode,
        top_k=max(CONTEXT_MAX_PAGES * 2, 16),
    )
    catalog_context = build_catalog_context_entries(catalog_candidates, max_items=max(2, CONTEXT_MAX_PAGES // 2))
    base_context = build_context_for_groq(
        search_queries[0],
        search_items,
        semantic_chunks=semantic_chunks,
        intent_mode=intent_mode,
        catalog_items=catalog_candidates,
    )
    context_primary = _merge_context_with_priority(tool_context, base_context, max_items=CONTEXT_MAX_PAGES * 2)
    context_pages = _merge_context_with_priority(context_primary, catalog_context, max_items=CONTEXT_MAX_PAGES)

    site_catalog = merged_catalog[: min(SITE_CATALOG_MAX_ITEMS, 80)]
    for item in tool_manifests[:20]:
        site_catalog.append(
            {
                "path": str(item.get("slug", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "title": str(item.get("name", "")).strip(),
                "section": "tools",
            }
        )

    cache_key = build_response_cache_key(
        message=message,
        channel=channel,
        intent_mode=intent_mode,
        language=language,
        context_pages=context_pages,
    )
    cached = await response_cache.get(cache_key)
    if isinstance(cached, dict):
        cached_payload = dict(cached)
        cached_payload["reason"] = (str(cached_payload.get("reason", "")).strip() + " cache-hit").strip()
        cached_payload["intent_mode"] = intent_mode
        cached_payload["experiment_variant"] = experiment_variant
        cached_payload["experiment_model"] = experiment_model
        cached_payload = apply_channel_guardrails(cached_payload, channel)
        await memory_store.add_turn(user_id or "", channel, message, str(cached_payload.get("answer", "")))
        await _record(
            True,
            float(cached_payload.get("confidence_score", 0.0) or 0.0),
            len(context_pages),
            str(cached_payload.get("reason", "")),
            intent=intent_mode,
            variant=experiment_variant,
            cache_hit=True,
        )
        return cached_payload

    try:
        result = await ask_groq_navigate(
            message,
            merged_history,
            context_pages,
            site_catalog,
            language,
            tutorial_mode=tutorial_mode,
            tool_manifest_context=tool_manifests,
            intent_mode=intent_mode,
            channel=channel,
            prompt_variant=experiment_variant,
            model_override=experiment_model,
        )
        result = enrich_navigation_result(result, context_pages, message)
        result["sources"] = build_response_sources(context_pages, max_items=3)
        result["confidence_score"] = estimate_confidence(
            message,
            context_pages,
            recommended_url=str(result.get("recommended_url", "")).strip(),
        )

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
            result["confidence_score"] = max(float(result.get("confidence_score", 0.0)), 0.62)

        confidence_now = float(result.get("confidence_score", 0.0) or 0.0)
        low_conf = confidence_now < LOW_CONFIDENCE_THRESHOLD and not tutorial_mode
        grounded = _is_grounded_enough(result, context_pages, message) if STRICT_GROUNDING_ENABLED else True
        if STRICT_GROUNDING_ENABLED and (not grounded):
            result["answer"] = _clarification_answer(language)
            result["recommended_url"] = ""
            result["recommended_type"] = "none"
            result["related_items"] = []
            result["sources"] = []
            result["reason"] = (str(result.get("reason", "")).strip() + " strict-grounding guardrail").strip()
            low_conf = True

        if low_conf:
            result["answer"] = _clarification_answer(language)
            result["recommended_url"] = ""
            result["recommended_type"] = "none"
            result["related_items"] = []
            result["reason"] = (str(result.get("reason", "")).strip() + " Low confidence; asked clarification.").strip()
            await learning_store.record_event(
                channel=channel,
                user_id=str(user_id or ""),
                message=message,
                answer=str(result.get("answer", "")),
                recommended_url=str(result.get("recommended_url", "")),
                confidence=float(result.get("confidence_score", 0.0) or 0.0),
                reason=str(result.get("reason", "")),
                intent_mode=intent_mode,
            )
            if HUMAN_HANDOFF_ENABLED and user_id:
                should_handoff = await handoff_state.bump_low_confidence(str(user_id))
                if should_handoff:
                    result["answer"] = _human_handoff_answer(language)
                    result["recommended_type"] = "page" if HUMAN_HANDOFF_CONTACT_URL else "none"
                    result["recommended_url"] = str(HUMAN_HANDOFF_CONTACT_URL or "").strip()
                    result["reason"] = (str(result.get("reason", "")).strip() + " handoff triggered").strip()
                    result["confidence_score"] = max(0.8, float(result.get("confidence_score", 0.0) or 0.0))
                    result["intent_mode"] = "handoff"
                    result["experiment_variant"] = experiment_variant
                    result["experiment_model"] = experiment_model
                    result = apply_channel_guardrails(result, channel)
                    await memory_store.add_turn(user_id or "", channel, message, str(result.get("answer", "")))
                    await _record(
                        True,
                        float(result.get("confidence_score", 0.0) or 0.0),
                        len(context_pages),
                        str(result.get("reason", "")),
                        intent="handoff",
                        variant=experiment_variant,
                        low_confidence=True,
                        handoff=True,
                        grounded=grounded,
                    )
                    return result
        else:
            if user_id:
                await handoff_state.reset(str(user_id))

        result["intent_mode"] = intent_mode
        result["experiment_variant"] = experiment_variant
        result["experiment_model"] = experiment_model
        if grounded and float(result.get("confidence_score", 0.0) or 0.0) >= STRICT_GROUNDING_MIN_CONFIDENCE:
            await response_cache.set(cache_key, result)
        result = apply_channel_guardrails(result, channel)

        await memory_store.add_turn(user_id or "", channel, message, str(result.get("answer", "")))
        await _record(
            True,
            float(result.get("confidence_score", 0.0) or 0.0),
            len(context_pages),
            str(result.get("reason", "")),
            intent=intent_mode,
            variant=experiment_variant,
            low_confidence=low_conf,
            grounded=grounded,
        )
        return result
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        logger.error("Groq HTTP error: %s", detail)
        fallback = not_found_response(language)
        fallback = enrich_navigation_result(fallback, context_pages, message)
        fallback["reason"] = f"Groq error fallback: {detail[:300]}"
        fallback["sources"] = build_response_sources(context_pages, max_items=2)
        fallback["confidence_score"] = estimate_confidence(
            message,
            context_pages,
            recommended_url=str(fallback.get("recommended_url", "")).strip(),
        )
        if tutorial_mode and tool_manifests:
            primary = tool_manifests[0]
            fallback["answer"] = _format_tutorial_fallback(primary, language)
            fallback["recommended_url"] = str(primary.get("url", "")).strip()
            fallback["recommended_type"] = "tool" if fallback["recommended_url"] else fallback.get("recommended_type", "none")
            fallback["confidence_score"] = max(float(fallback.get("confidence_score", 0.0)), 0.58)
        await learning_store.record_event(
            channel=channel,
            user_id=str(user_id or ""),
            message=message,
            answer=str(fallback.get("answer", "")),
            recommended_url=str(fallback.get("recommended_url", "")),
            confidence=float(fallback.get("confidence_score", 0.0) or 0.0),
            reason=str(fallback.get("reason", "")),
            intent_mode=intent_mode,
        )
        fallback["intent_mode"] = intent_mode
        fallback["experiment_variant"] = experiment_variant
        fallback["experiment_model"] = experiment_model
        fallback = apply_channel_guardrails(fallback, channel)
        await memory_store.add_turn(user_id or "", channel, message, str(fallback.get("answer", "")))
        await _record(
            False,
            float(fallback.get("confidence_score", 0.0) or 0.0),
            len(context_pages),
            str(fallback.get("reason", "")),
            intent=intent_mode,
            variant=experiment_variant,
            grounded=False,
        )
        return fallback
    except Exception as e:
        logger.exception("Unexpected AI error")
        fallback = not_found_response(language)
        fallback = enrich_navigation_result(fallback, context_pages, message)
        fallback["reason"] = f"AI error fallback: {str(e)[:300]}"
        fallback["sources"] = build_response_sources(context_pages, max_items=2)
        fallback["confidence_score"] = estimate_confidence(
            message,
            context_pages,
            recommended_url=str(fallback.get("recommended_url", "")).strip(),
        )
        if tutorial_mode and tool_manifests:
            primary = tool_manifests[0]
            fallback["answer"] = _format_tutorial_fallback(primary, language)
            fallback["recommended_url"] = str(primary.get("url", "")).strip()
            fallback["recommended_type"] = "tool" if fallback["recommended_url"] else fallback.get("recommended_type", "none")
            fallback["confidence_score"] = max(float(fallback.get("confidence_score", 0.0)), 0.58)
        await learning_store.record_event(
            channel=channel,
            user_id=str(user_id or ""),
            message=message,
            answer=str(fallback.get("answer", "")),
            recommended_url=str(fallback.get("recommended_url", "")),
            confidence=float(fallback.get("confidence_score", 0.0) or 0.0),
            reason=str(fallback.get("reason", "")),
            intent_mode=intent_mode,
        )
        fallback["intent_mode"] = intent_mode
        fallback["experiment_variant"] = experiment_variant
        fallback["experiment_model"] = experiment_model
        fallback = apply_channel_guardrails(fallback, channel)
        await memory_store.add_turn(user_id or "", channel, message, str(fallback.get("answer", "")))
        await _record(
            False,
            float(fallback.get("confidence_score", 0.0) or 0.0),
            len(context_pages),
            str(fallback.get("reason", "")),
            intent=intent_mode,
            variant=experiment_variant,
            grounded=False,
        )
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


def _extract_openai_user_id(payload: Dict[str, Any]) -> str:
    return _extract_first_non_empty(
        payload,
        [
            "user",
            "metadata.user.id",
            "metadata.user_id",
            "metadata.sender.id",
            "metadata.sender_id",
            "metadata.sender",
            "metadata.contact",
            "metadata.phone",
            "metadata.from",
            "conversation.user.id",
            "conversation.user_id",
            "conversation.sender.id",
            "conversation.sender_id",
            "conversation.from",
            "context.user.id",
            "context.user_id",
            "context.sender.id",
            "context.sender_id",
            "context.from",
            "sender.id",
            "sender_id",
            "from",
            "contact.phone",
            "contact.id",
            "wa.from",
            "wa.sender",
            "wa.sender_id",
            "session_id",
            "thread_id",
            "conversation_id",
        ],
    )


def _normalize_phone_token(raw: str) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    digits = "".join(ch for ch in token if ch.isdigit())
    if len(digits) < 9:
        return ""
    return f"+{digits}"


def _extract_phone_token(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    match = _PHONE_TOKEN_RE.search(value)
    if not match:
        return ""
    return _normalize_phone_token(match.group(1))


def _extract_sender_id_hint(payload: Any) -> str:
    key_hints = {"from", "sender", "user", "author", "contact", "phone", "jid", "wa"}
    best: str = ""

    def walk(node: Any, path: str = ""):
        nonlocal best
        if best:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                walk(value, child_path)
                if best:
                    return
            return
        if isinstance(node, list):
            for idx, item in enumerate(node):
                child_path = f"{path}[{idx}]"
                walk(item, child_path)
                if best:
                    return
            return
        if not isinstance(node, str):
            return
        lower_path = path.lower()
        if not any(h in lower_path for h in key_hints):
            return
        phone = _extract_phone_token(node)
        if phone:
            best = phone

    walk(payload)
    return best


def _resolve_openai_sender_id(payload: Dict[str, Any], message: str, extracted_user_id: str) -> str:
    # Prefer explicit sender phone from payload when available.
    direct = str(extracted_user_id or "").strip()
    direct_phone = _extract_phone_token(direct)
    if direct_phone:
        return direct_phone

    # Then parse sender phone from inbound text wrapper.
    from_message = _extract_phone_token(message)
    if from_message:
        return from_message

    # Then deep scan payload fields likely containing sender identifiers.
    from_payload = _extract_sender_id_hint(payload)
    if from_payload:
        return from_payload

    # Last fallback for non-phone identifiers.
    if direct:
        lowered = direct.lower()
        if lowered not in {"anonymous", "session", "thread", "conversation"} and not lowered.startswith("session_"):
            return direct

    return ""


def resolve_sender_id(payload: Dict[str, Any], message: str, extracted_user_id: str) -> str:
    return _resolve_openai_sender_id(payload, message, extracted_user_id)


def _strip_required_prefix(message: str, prefix: str) -> tuple[bool, str]:
    raw = str(message or "")
    required = str(prefix or "").strip()
    if not required:
        return True, raw.strip()

    # Accept common chat separators and tolerate wrapper text before prefix
    # (some channel connectors prepend sender metadata).
    # Examples:
    # - "/ia hi"
    # - "From +62: /ia hi"
    # - "[DM] /ia: hi"
    pattern = re.compile(
        rf"(^|[\s<>\[\]\(\)\{{\}},;:|]){re.escape(required)}(?=$|[\s:;,\-–—.!?])",
        flags=re.IGNORECASE,
    )
    matched = pattern.search(raw)
    if not matched:
        return False, raw.strip()

    rest = raw[matched.end() :]
    rest = rest.lstrip(" \t\r\n:;,-–—.!?")
    return True, rest.strip()


async def _evaluate_openclaw_prefix_gate(message: str, sender_id: str) -> Dict[str, str]:
    if not OPENCLAW_PREFIX_GATE_ENABLED:
        return {"action": "proceed", "message": message}

    prefixed, stripped = _strip_required_prefix(message, OPENCLAW_REQUIRED_PREFIX)
    language = detect_language(message, [])
    reminder_template = OPENCLAW_PREFIX_REMINDER_TEXT_EN if language == "en" else OPENCLAW_PREFIX_REMINDER_TEXT
    if prefixed and stripped:
        return {"action": "proceed", "message": stripped}
    if prefixed and not stripped:
        reminder = reminder_template.format(prefix=OPENCLAW_REQUIRED_PREFIX)
        return {"action": "reply", "message": reminder}

    should_remind = await prefix_gate_store.should_send_reminder(sender_id)
    if should_remind:
        reminder = reminder_template.format(prefix=OPENCLAW_REQUIRED_PREFIX)
        return {"action": "reply", "message": reminder}
    if OPENCLAW_PREFIX_GATE_HARD_IGNORE:
        return {"action": "drop", "message": ""}
    return {"action": "silent", "message": ""}


async def evaluate_openclaw_prefix_gate(message: str, sender_id: str) -> Dict[str, str]:
    return await _evaluate_openclaw_prefix_gate(message, sender_id)


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


def _build_openai_completion_response(
    *,
    answer: str,
    model: str,
    stream: bool,
):
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


async def build_openai_chat_completion(payload: Dict[str, Any]) -> Any:
    model = str(payload.get("model") or OPENCLAW_COMPAT_MODEL_ID)
    stream = bool(payload.get("stream", False))

    parsed = openai_messages_to_internal(payload.get("messages", []))
    message = str(parsed.get("message", "")).strip()
    history = parsed.get("history", [])
    user_id = _extract_openai_user_id(payload)
    sender_id = resolve_sender_id(payload, message, user_id)
    effective_user_id = sender_id or (user_id or None)

    if not message:
        raise HTTPException(status_code=422, detail="Invalid payload: user message is required")

    gate = await evaluate_openclaw_prefix_gate(message, sender_id)
    gate_action = str(gate.get("action", "proceed")).strip()
    await observability.record_prefix_gate(gate_action)
    if OPENCLAW_PREFIX_GATE_ENABLED:
        logger.info(
            "[prefix-gate] action=%s sender=%s message_len=%d",
            gate_action,
            (sender_id[:5] + "***") if sender_id else "(missing)",
            len(message),
        )
    if gate_action == "reply":
        answer = str(gate.get("message", "")).strip()
        return _build_openai_completion_response(answer=answer, model=model, stream=stream)
    if gate_action in {"silent", "drop"}:
        return _build_openai_completion_response(answer="", model=model, stream=stream)
    message = str(gate.get("message", message)).strip()
    if not message:
        return _build_openai_completion_response(answer="", model=model, stream=stream)

    ai_result = await generate_chat_response(message, history, user_id=effective_user_id, channel="openai")
    language = detect_language(message, history)
    presented = present_ai_result(ai_result, language, channel="openai")
    answer = str(presented.get("answer", "")).strip()
    return _build_openai_completion_response(answer=answer, model=model, stream=stream)
