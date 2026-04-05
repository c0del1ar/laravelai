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
        normalized = [item for item in items if isinstance(item, dict)]

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
                return payload
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
    return [dict(item) for _, item in scored[:top_k]]
