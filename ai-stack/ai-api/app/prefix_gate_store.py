import asyncio
import json
import os
import time
from typing import Dict

from .config import OPENCLAW_PREFIX_GATE_STORE_PATH, OPENCLAW_PREFIX_REMINDER_COOLDOWN_SECONDS


class PrefixGateStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._last_notice_ts: Dict[str, float] = {}

    async def load(self):
        async with self._lock:
            try:
                with open(OPENCLAW_PREFIX_GATE_STORE_PATH, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return
            raw = payload.get("last_notice_ts", {})
            if isinstance(raw, dict):
                parsed = {}
                for k, v in raw.items():
                    try:
                        parsed[str(k)] = float(v)
                    except Exception:
                        continue
                self._last_notice_ts = parsed

    async def _save(self):
        parent = os.path.dirname(OPENCLAW_PREFIX_GATE_STORE_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {"last_notice_ts": self._last_notice_ts}
        try:
            with open(OPENCLAW_PREFIX_GATE_STORE_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except Exception:
            pass

    async def should_send_reminder(self, sender_id: str) -> bool:
        sid = str(sender_id or "").strip()
        if not sid:
            return True
        now = time.time()
        cooldown = max(60, OPENCLAW_PREFIX_REMINDER_COOLDOWN_SECONDS)
        async with self._lock:
            prev = float(self._last_notice_ts.get(sid, 0.0) or 0.0)
            if prev <= 0.0 or (now - prev) >= cooldown:
                self._last_notice_ts[sid] = now
                await self._save()
                return True
            return False

    async def stats(self) -> Dict[str, int]:
        async with self._lock:
            return {"tracked_senders": len(self._last_notice_ts)}


prefix_gate_store = PrefixGateStore()
