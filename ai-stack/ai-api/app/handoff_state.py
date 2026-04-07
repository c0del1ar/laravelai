import asyncio
import json
import os
import time
from typing import Dict

from .config import HUMAN_HANDOFF_LOW_CONF_STREAK, HUMAN_HANDOFF_STATE_PATH, MEMORY_TTL_SECONDS


class HandoffStateStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._streaks: Dict[str, Dict[str, float]] = {}

    async def load(self):
        async with self._lock:
            try:
                with open(HUMAN_HANDOFF_STATE_PATH, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return
            raw = payload.get("streaks", {})
            if not isinstance(raw, dict):
                return
            parsed: Dict[str, Dict[str, float]] = {}
            for key, value in raw.items():
                if not isinstance(value, dict):
                    continue
                count = int(value.get("count", 0) or 0)
                ts = float(value.get("ts", 0.0) or 0.0)
                if count > 0:
                    parsed[str(key)] = {"count": count, "ts": ts}
            self._streaks = parsed
            self._prune_locked()

    def _prune_locked(self):
        ttl = max(600, MEMORY_TTL_SECONDS)
        cutoff = time.time() - ttl
        to_delete = [
            key for key, value in self._streaks.items()
            if float((value or {}).get("ts", 0.0) or 0.0) < cutoff
        ]
        for key in to_delete:
            self._streaks.pop(key, None)

    async def _save_locked(self):
        parent = os.path.dirname(HUMAN_HANDOFF_STATE_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            with open(HUMAN_HANDOFF_STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump({"streaks": self._streaks}, fh, ensure_ascii=False)
        except Exception:
            pass

    async def bump_low_confidence(self, user_id: str) -> bool:
        uid = str(user_id or "").strip()
        if not uid:
            return False
        threshold = max(1, HUMAN_HANDOFF_LOW_CONF_STREAK)
        async with self._lock:
            self._prune_locked()
            state = dict(self._streaks.get(uid, {}))
            count = int(state.get("count", 0) or 0) + 1
            self._streaks[uid] = {"count": count, "ts": time.time()}
            await self._save_locked()
            return count >= threshold

    async def reset(self, user_id: str):
        uid = str(user_id or "").strip()
        if not uid:
            return
        async with self._lock:
            self._streaks.pop(uid, None)
            await self._save_locked()

    async def stats(self) -> Dict[str, int]:
        async with self._lock:
            self._prune_locked()
            return {"tracked_users": len(self._streaks)}


handoff_state = HandoffStateStore()
