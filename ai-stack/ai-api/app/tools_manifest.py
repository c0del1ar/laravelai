import asyncio
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import httpx

from .config import SEARCH_API_KEY, TOOL_MANIFEST_API_URL, TOOL_MANIFEST_MAX_ITEMS, TOOL_MANIFEST_TTL
from .html_utils import tokenize_for_search
from .nlp import normalize_text


_cache_lock = asyncio.Lock()
_manifest_cache: Dict[str, Any] = {
    "loaded_at": 0.0,
    "items": [],
}


def _normalize_manifest_item(item: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(item) if isinstance(item, dict) else {}
    playbook = source.get("playbook", {})
    playbook = playbook if isinstance(playbook, dict) else {}
    playbook_i18n = source.get("playbook_i18n", {})
    playbook_i18n = playbook_i18n if isinstance(playbook_i18n, dict) else {}
    playbook_i18n_id = playbook_i18n.get("id", {})
    playbook_i18n_en = playbook_i18n.get("en", {})
    playbook_i18n_id = playbook_i18n_id if isinstance(playbook_i18n_id, dict) else {}
    playbook_i18n_en = playbook_i18n_en if isinstance(playbook_i18n_en, dict) else {}
    hook = source.get("hook", {})
    hook = hook if isinstance(hook, dict) else {}
    input_schema = source.get("input_schema", {})
    input_schema = input_schema if isinstance(input_schema, dict) else {}
    fields = input_schema.get("fields", [])
    fields = fields if isinstance(fields, list) else []
    clean_fields: List[Dict[str, Any]] = []
    for field in fields[:30]:
        if not isinstance(field, dict):
            continue
        clean_fields.append(
            {
                "key": str(field.get("key", "")).strip(),
                "label": str(field.get("label", "")).strip(),
                "type": str(field.get("type", "text")).strip() or "text",
                "required": bool(field.get("required", False)),
                "placeholder": str(field.get("placeholder", "")).strip(),
                "hint": str(field.get("hint", "")).strip(),
            }
        )

    steps = source.get("steps", [])
    steps = [str(v).strip() for v in steps if str(v).strip()] if isinstance(steps, list) else []
    pb_steps = playbook.get("steps", [])
    pb_steps = [str(v).strip() for v in pb_steps if str(v).strip()] if isinstance(pb_steps, list) else []
    merged_steps = list(dict.fromkeys((steps + pb_steps)))[:14]

    return {
        "slug": str(source.get("slug", "")).strip(),
        "name": str(source.get("name", "")).strip(),
        "url": str(source.get("url", "")).strip(),
        "description": str(source.get("description", "")).strip(),
        "category": str(source.get("category", "")).strip(),
        "input_schema": {"fields": clean_fields},
        "steps": merged_steps,
        "output_explained": str(source.get("output_explained", "")).strip(),
        "playbook": {
            "what_it_does": str(playbook.get("what_it_does", "")).strip(),
            "input_tips": [str(v).strip() for v in (playbook.get("input_tips", []) or []) if str(v).strip()][:16],
            "troubleshooting": [str(v).strip() for v in (playbook.get("troubleshooting", []) or []) if str(v).strip()][:16],
        },
        "playbook_i18n": {
            "id": {
                "what_it_does": str(playbook_i18n_id.get("what_it_does", "")).strip(),
                "input_tips": [str(v).strip() for v in (playbook_i18n_id.get("input_tips", []) or []) if str(v).strip()][:16],
                "troubleshooting": [str(v).strip() for v in (playbook_i18n_id.get("troubleshooting", []) or []) if str(v).strip()][:16],
            },
            "en": {
                "what_it_does": str(playbook_i18n_en.get("what_it_does", "")).strip(),
                "input_tips": [str(v).strip() for v in (playbook_i18n_en.get("input_tips", []) or []) if str(v).strip()][:16],
                "troubleshooting": [str(v).strip() for v in (playbook_i18n_en.get("troubleshooting", []) or []) if str(v).strip()][:16],
            },
        },
        "hook": {
            "tips": [str(v).strip() for v in (hook.get("tips", []) or []) if str(v).strip()][:16],
            "examples": [
                {
                    "label": str((example or {}).get("label", "")).strip(),
                    "value": str((example or {}).get("value", "")).strip(),
                }
                for example in (hook.get("examples", []) or [])[:16]
                if isinstance(example, dict)
            ],
        },
    }


def _manifest_to_search_text(item: Dict[str, Any]) -> str:
    parts: List[str] = [
        str(item.get("slug", "")),
        str(item.get("name", "")),
        str(item.get("description", "")),
        str(item.get("category", "")),
    ]

    input_schema = item.get("input_schema", {})
    fields = input_schema.get("fields", []) if isinstance(input_schema, dict) else []
    for field in fields[:20]:
        if not isinstance(field, dict):
            continue
        parts.append(str(field.get("key", "")))
        parts.append(str(field.get("label", "")))
        parts.append(str(field.get("type", "")))
        parts.append(str(field.get("placeholder", "")))
        parts.append(str(field.get("hint", "")))

    for step in (item.get("steps", []) if isinstance(item.get("steps", []), list) else [])[:10]:
        parts.append(str(step))

    playbook = item.get("playbook", {})
    if isinstance(playbook, dict):
        parts.append(str(playbook.get("what_it_does", "")))
        for step in (playbook.get("steps", []) if isinstance(playbook.get("steps", []), list) else [])[:10]:
            parts.append(str(step))
        for tip in (playbook.get("input_tips", []) if isinstance(playbook.get("input_tips", []), list) else [])[:12]:
            parts.append(str(tip))
        for issue in (playbook.get("troubleshooting", []) if isinstance(playbook.get("troubleshooting", []), list) else [])[:12]:
            parts.append(str(issue))

    playbook_i18n = item.get("playbook_i18n", {})
    if isinstance(playbook_i18n, dict):
        for locale in ("id", "en"):
            localized = playbook_i18n.get(locale, {})
            if not isinstance(localized, dict):
                continue
            parts.append(str(localized.get("what_it_does", "")))
            for tip in (localized.get("input_tips", []) if isinstance(localized.get("input_tips", []), list) else [])[:12]:
                parts.append(str(tip))
            for issue in (localized.get("troubleshooting", []) if isinstance(localized.get("troubleshooting", []), list) else [])[:12]:
                parts.append(str(issue))

    hook = item.get("hook", {})
    if isinstance(hook, dict):
        for tip in (hook.get("tips", []) if isinstance(hook.get("tips", []), list) else [])[:12]:
            parts.append(str(tip))
        for example in (hook.get("examples", []) if isinstance(hook.get("examples", []), list) else [])[:12]:
            if isinstance(example, dict):
                parts.append(str(example.get("label", "")))
                parts.append(str(example.get("value", "")))

    return normalize_text(" ".join(parts))


def _score_manifest_item(query: str, item: Dict[str, Any]) -> float:
    terms = tokenize_for_search(query)
    if not terms:
        return 0.0

    name_tokens = tokenize_for_search(str(item.get("name", "")))
    slug_tokens = tokenize_for_search(str(item.get("slug", "")).replace("-", " "))
    text_tokens = tokenize_for_search(_manifest_to_search_text(item))
    tf = Counter(text_tokens)

    score = 0.0
    for term in terms:
        if term in slug_tokens:
            score += 6.0
        if term in name_tokens:
            score += 5.0
        count = min(tf.get(term, 0), 6)
        if count:
            score += 1.5 * count

    if len(terms) == 1:
        term = terms[0]
        slug = normalize_text(str(item.get("slug", "")).replace("-", " "))
        if term and term in slug:
            score += 3.0

    return score


async def fetch_tools_manifest(force: bool = False) -> List[Dict[str, Any]]:
    if not TOOL_MANIFEST_API_URL:
        return []

    now = time.time()
    if not force and _manifest_cache["items"] and (now - float(_manifest_cache["loaded_at"])) < TOOL_MANIFEST_TTL:
        return [dict(v) for v in _manifest_cache["items"]]

    async with _cache_lock:
        now = time.time()
        if not force and _manifest_cache["items"] and (now - float(_manifest_cache["loaded_at"])) < TOOL_MANIFEST_TTL:
            return [dict(v) for v in _manifest_cache["items"]]

        headers = {"X-Search-Key": SEARCH_API_KEY} if SEARCH_API_KEY else {}
        params = {"limit": max(1, min(TOOL_MANIFEST_MAX_ITEMS, 300))}

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(TOOL_MANIFEST_API_URL, params=params, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except Exception:
            return [dict(v) for v in _manifest_cache["items"]]

        items = payload.get("items", []) if isinstance(payload, dict) else []
        items = items if isinstance(items, list) else []
        normalized = [_normalize_manifest_item(item) for item in items if isinstance(item, dict)]

        _manifest_cache["items"] = normalized
        _manifest_cache["loaded_at"] = time.time()
        return [dict(v) for v in normalized]


async def fetch_tool_manifest_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    slug = slug.strip().strip("/")
    if not slug:
        return None

    items = await fetch_tools_manifest()
    for item in items:
        if normalize_text(str(item.get("slug", ""))) == normalize_text(slug):
            return dict(item)

    if not TOOL_MANIFEST_API_URL:
        return None

    base = TOOL_MANIFEST_API_URL.rstrip("/")
    headers = {"X-Search-Key": SEARCH_API_KEY} if SEARCH_API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/{slug}", headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict):
                return _normalize_manifest_item(payload)
    except Exception:
        return None

    return None


async def find_relevant_tool_manifests(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    items = await fetch_tools_manifest()
    if not items:
        return []

    scored: List[tuple] = []
    for item in items:
        score = _score_manifest_item(query, item)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [_normalize_manifest_item(item) for _, item in scored[:top_k]]
