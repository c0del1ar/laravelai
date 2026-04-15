import asyncio
import time
from collections import Counter
from typing import Any, Dict, List, Set

import httpx

from .config import CATALOG_API_KEY, CATALOG_API_URL, CATALOG_MAX_ITEMS, CATALOG_TTL, SEARCH_API_KEY
from .html_utils import normalize_path, tokenize_for_search
from .nlp import normalize_text, query_terms


_catalog_lock = asyncio.Lock()
_catalog_cache: Dict[str, Any] = {
    "loaded_at": 0.0,
    "items": [],
}


def _normalize_catalog_item(item: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(item) if isinstance(item, dict) else {}
    raw_url = str(source.get("url", "")).strip()
    raw_path = str(source.get("path", "")).strip()
    path = normalize_path(raw_path or raw_url)
    if raw_url and raw_url.startswith(("http://", "https://")):
        url = raw_url
    else:
        url = normalize_path(raw_url or path)

    summary = str(source.get("summary", "")).strip()
    keywords = source.get("keywords", [])
    keywords = [str(v).strip() for v in keywords if str(v).strip()] if isinstance(keywords, list) else []

    return {
        "type": str(source.get("type", "page")).strip() or "page",
        "section": str(source.get("section", "general")).strip() or "general",
        "title": str(source.get("title", "")).strip() or path,
        "url": url,
        "path": path,
        "summary": summary,
        "keywords": keywords[:24],
        "updated_at": str(source.get("updated_at", "")).strip(),
    }


async def fetch_site_catalog(force: bool = False) -> List[Dict[str, Any]]:
    if not CATALOG_API_URL:
        return []

    now = time.time()
    if not force and _catalog_cache["items"] and (now - float(_catalog_cache["loaded_at"])) < CATALOG_TTL:
        return [dict(v) for v in _catalog_cache["items"]]

    async with _catalog_lock:
        now = time.time()
        if not force and _catalog_cache["items"] and (now - float(_catalog_cache["loaded_at"])) < CATALOG_TTL:
            return [dict(v) for v in _catalog_cache["items"]]

        key = CATALOG_API_KEY or SEARCH_API_KEY
        headers = {"X-Search-Key": key} if key else {}
        params = {"limit": max(1, min(CATALOG_MAX_ITEMS, 500))}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(CATALOG_API_URL, headers=headers, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return [dict(v) for v in _catalog_cache["items"]]

        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            items = []
        normalized = [_normalize_catalog_item(item) for item in items if isinstance(item, dict)]
        normalized = [item for item in normalized if str(item.get("url", "")).strip()]
        normalized = normalized[: max(1, min(CATALOG_MAX_ITEMS, 500))]

        _catalog_cache["items"] = normalized
        _catalog_cache["loaded_at"] = time.time()
        return [dict(v) for v in normalized]


def merge_site_catalogs(
    local_items: List[Dict[str, Any]],
    remote_items: List[Dict[str, Any]],
    max_items: int = 200,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in (remote_items or []) + (local_items or []):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_catalog_item(item)
        key = str(normalized.get("url", "")).strip() or str(normalized.get("path", "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
        if len(merged) >= max(1, min(max_items, 500)):
            break
    return merged


def _intent_section_boost(intent_mode: str, section: str, text: str) -> float:
    sec = normalize_text(section)
    full = normalize_text(text)
    if intent_mode == "pricing":
        return 1.3 if "pricing" in sec or "harga" in full or "plan" in full else 0.0
    if intent_mode == "contact":
        return 1.3 if "contact" in sec or "kontak" in full or "support" in full else 0.0
    if intent_mode == "tutorial":
        return 1.1 if "tools" in sec or "tool" in full or "checker" in full else 0.0
    if intent_mode == "blog":
        return 1.1 if "blog" in sec or "artikel" in full else 0.0
    if intent_mode == "product":
        return 1.0 if "product" in sec or "produk" in full else 0.0
    if intent_mode == "about":
        return 0.9 if "about" in sec or "tentang" in full else 0.0
    if intent_mode == "feature":
        return 0.8 if "feature" in full or "fitur" in full else 0.0
    return 0.0


def rank_catalog_items(
    query: str,
    catalog_items: List[Dict[str, Any]],
    intent_mode: str = "navigation",
    top_k: int = 20,
) -> List[Dict[str, Any]]:
    if not catalog_items:
        return []

    terms = query_terms(query)
    if not terms:
        terms = tokenize_for_search(query)
    if not terms:
        return catalog_items[:top_k]

    scored: List[Dict[str, Any]] = []
    for item in catalog_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        path = str(item.get("path", "")).strip()
        section = str(item.get("section", "")).strip()
        summary = str(item.get("summary", "")).strip()
        keywords = item.get("keywords", [])
        keywords = [str(v).strip() for v in keywords if str(v).strip()] if isinstance(keywords, list) else []
        joined = " ".join([title, path, section, summary, " ".join(keywords)])
        tokens = tokenize_for_search(joined)
        tf = Counter(tokens)
        title_tokens = set(tokenize_for_search(title))
        path_tokens = set(tokenize_for_search(path.replace("/", " ")))

        score = 0.0
        for term in terms:
            if term in title_tokens:
                score += 3.2
            if term in path_tokens:
                score += 2.6
            score += 1.1 * min(tf.get(term, 0), 4)

        score += _intent_section_boost(intent_mode, section, joined)
        if score > 0:
            payload = _normalize_catalog_item(item)
            payload["score"] = round(score, 4)
            scored.append(payload)

    scored.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return scored[: max(1, top_k)]


def build_catalog_context_entries(items: List[Dict[str, Any]], max_items: int = 4) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for item in items[: max(1, max_items)]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        summary = str(item.get("summary", "")).strip()
        keywords = item.get("keywords", [])
        if isinstance(keywords, list) and keywords:
            summary = (summary + " Keywords: " + ", ".join(str(v).strip() for v in keywords[:10] if str(v).strip())).strip()
        entries.append(
            {
                "title": str(item.get("title", "")).strip() or url,
                "url": url,
                "summary": summary,
                "content": summary,
                "source": "catalog-structured",
            }
        )
    return entries


def site_catalog_cache_stats() -> Dict[str, Any]:
    loaded_at = float(_catalog_cache.get("loaded_at", 0.0) or 0.0)
    return {
        "cache_items": len(_catalog_cache.get("items", []) or []),
        "cache_loaded_at": int(loaded_at) if loaded_at > 0 else 0,
        "cache_age_sec": int(max(0.0, time.time() - loaded_at)) if loaded_at > 0 else 0,
        "api_url_configured": bool(CATALOG_API_URL),
    }
