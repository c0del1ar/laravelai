import asyncio
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

from .config import (
    RESPONSE_CACHE_ENABLED,
    RESPONSE_CACHE_MAX_ITEMS,
    RESPONSE_CACHE_PATH,
    RESPONSE_CACHE_TTL_SECONDS,
)
from .nlp import normalize_text


class ResponseCacheStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._items: Dict[str, Dict[str, Any]] = {}

    async def load(self):
        async with self._lock:
            try:
                with open(RESPONSE_CACHE_PATH, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return
            raw = payload.get("items", {})
            if isinstance(raw, dict):
                parsed: Dict[str, Dict[str, Any]] = {}
                for key, value in raw.items():
                    if not isinstance(value, dict):
                        continue
                    result = value.get("result")
                    ts = float(value.get("ts", 0.0) or 0.0)
                    if isinstance(result, dict) and ts > 0:
                        parsed[str(key)] = {"result": dict(result), "ts": ts}
                self._items = parsed
            self._prune_locked()

    def _prune_locked(self):
        ttl = max(30, RESPONSE_CACHE_TTL_SECONDS)
        cutoff = time.time() - ttl
        to_delete = [k for k, v in self._items.items() if float(v.get("ts", 0.0) or 0.0) < cutoff]
        for key in to_delete:
            self._items.pop(key, None)
        if len(self._items) <= max(100, RESPONSE_CACHE_MAX_ITEMS):
            return
        ordered = sorted(self._items.items(), key=lambda item: float((item[1] or {}).get("ts", 0.0)))
        overflow = len(self._items) - max(100, RESPONSE_CACHE_MAX_ITEMS)
        for idx in range(max(0, overflow)):
            self._items.pop(str(ordered[idx][0]), None)

    async def _save_locked(self):
        parent = os.path.dirname(RESPONSE_CACHE_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {"items": self._items}
        try:
            with open(RESPONSE_CACHE_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except Exception:
            pass

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not RESPONSE_CACHE_ENABLED:
            return None
        cache_key = str(key or "").strip()
        if not cache_key:
            return None
        async with self._lock:
            self._prune_locked()
            item = self._items.get(cache_key)
            if not isinstance(item, dict):
                return None
            result = item.get("result")
            if not isinstance(result, dict):
                return None
            return dict(result)

    async def set(self, key: str, result: Dict[str, Any]):
        if not RESPONSE_CACHE_ENABLED:
            return
        cache_key = str(key or "").strip()
        if not cache_key:
            return
        if not isinstance(result, dict):
            return
        async with self._lock:
            self._items[cache_key] = {"result": dict(result), "ts": time.time()}
            self._prune_locked()
            await self._save_locked()

    async def stats(self) -> Dict[str, int]:
        async with self._lock:
            self._prune_locked()
            return {"entries": len(self._items)}


def build_response_cache_key(
    *,
    message: str,
    channel: str,
    intent_mode: str,
    language: str,
    context_pages: List[Dict[str, Any]],
) -> str:
    normalized_q = normalize_text(message)
    url_fingerprint = "|".join(
        sorted(
            {
                str(item.get("url", "")).strip()
                for item in (context_pages or [])[:6]
                if isinstance(item, dict) and str(item.get("url", "")).strip()
            }
        )
    )
    raw = f"{channel}|{intent_mode}|{language}|{normalized_q}|{url_fingerprint}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"resp:{digest}"


response_cache = ResponseCacheStore()
