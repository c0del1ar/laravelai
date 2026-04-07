import asyncio
import time
from typing import Dict, List, Set

from .config import AUTO_INDEX_DEBOUNCE_SECONDS, AUTO_INDEX_ENABLED, AUTO_INDEX_MAX_BATCH
from .knowledge_base import kb


class IndexEventQueue:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._pending: Set[str] = set()
        self._flushing = False
        self._last_flush_at = 0.0
        self._stats: Dict[str, int] = {
            "queued_paths": 0,
            "flush_count": 0,
            "updated": 0,
            "removed": 0,
            "errors": 0,
        }

    async def enqueue(self, paths: List[str]) -> Dict[str, int]:
        if not AUTO_INDEX_ENABLED:
            return {"accepted": 0, "pending": 0}
        cleaned = [str(p or "").strip() for p in paths if str(p or "").strip()]
        if not cleaned:
            return {"accepted": 0, "pending": len(self._pending)}
        async with self._lock:
            before = len(self._pending)
            for path in cleaned:
                self._pending.add(path)
            accepted = len(self._pending) - before
            self._stats["queued_paths"] += accepted
            should_start = not self._flushing
            if should_start:
                self._flushing = True
                asyncio.create_task(self._flush_worker())
            return {"accepted": accepted, "pending": len(self._pending)}

    async def _flush_worker(self):
        try:
            while True:
                await asyncio.sleep(max(1, AUTO_INDEX_DEBOUNCE_SECONDS))
                async with self._lock:
                    batch = list(self._pending)[: max(1, AUTO_INDEX_MAX_BATCH)]
                    for path in batch:
                        self._pending.discard(path)
                if not batch:
                    async with self._lock:
                        self._flushing = False
                    return
                try:
                    result = await kb.refresh_paths(batch)
                    async with self._lock:
                        self._stats["flush_count"] += 1
                        self._stats["updated"] += int(result.get("updated", 0) or 0)
                        self._stats["removed"] += int(result.get("removed", 0) or 0)
                        self._last_flush_at = time.time()
                except Exception:
                    async with self._lock:
                        self._stats["errors"] += 1
        finally:
            async with self._lock:
                self._flushing = False

    async def stats(self) -> Dict[str, int]:
        async with self._lock:
            payload = dict(self._stats)
            payload["pending"] = len(self._pending)
            payload["flushing"] = 1 if self._flushing else 0
            payload["last_flush_at"] = int(self._last_flush_at) if self._last_flush_at else 0
            return payload


index_event_queue = IndexEventQueue()
