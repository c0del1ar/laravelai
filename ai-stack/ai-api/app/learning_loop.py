import asyncio
import json
import time
import uuid
from typing import Any, Dict, List

from .config import LEARNING_MAX_EVENTS, LEARNING_STORE_PATH


class LearningLoopStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._events: List[Dict[str, Any]] = []

    async def load(self):
        async with self._lock:
            try:
                with open(LEARNING_STORE_PATH, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return
            raw = payload.get("events", [])
            if isinstance(raw, list):
                self._events = [item for item in raw if isinstance(item, dict)][-LEARNING_MAX_EVENTS:]

    async def _save(self):
        try:
            with open(LEARNING_STORE_PATH, "w", encoding="utf-8") as fh:
                json.dump({"events": self._events[-LEARNING_MAX_EVENTS:]}, fh, ensure_ascii=False)
        except Exception:
            pass

    async def record_event(
        self,
        *,
        channel: str,
        user_id: str,
        message: str,
        answer: str,
        recommended_url: str,
        confidence: float,
        reason: str,
        intent_mode: str,
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        event = {
            "id": event_id,
            "ts": int(time.time()),
            "channel": channel,
            "user_id": user_id,
            "message": message[:1200],
            "answer": answer[:2000],
            "recommended_url": recommended_url[:400],
            "confidence": float(confidence),
            "reason": reason[:400],
            "intent_mode": intent_mode,
            "status": "open",
            "correction": None,
        }
        async with self._lock:
            self._events.append(event)
            self._events = self._events[-LEARNING_MAX_EVENTS:]
            await self._save()
        return event_id

    async def list_open(self, limit: int = 100) -> List[Dict[str, Any]]:
        async with self._lock:
            items = [dict(item) for item in self._events if str(item.get("status", "")) == "open"]
        items.sort(key=lambda x: int(x.get("ts", 0)), reverse=True)
        return items[: max(1, min(limit, 500))]

    async def apply_correction(self, event_id: str, corrected_answer: str, corrected_url: str, tags: List[str]) -> bool:
        async with self._lock:
            for item in self._events:
                if str(item.get("id", "")) != event_id:
                    continue
                item["status"] = "corrected"
                item["correction"] = {
                    "answer": str(corrected_answer).strip()[:2200],
                    "url": str(corrected_url).strip()[:400],
                    "tags": [str(v).strip()[:40] for v in tags if str(v).strip()][:10],
                    "ts": int(time.time()),
                }
                await self._save()
                return True
        return False

    async def export_jsonl(self, max_items: int = 1000) -> str:
        async with self._lock:
            items = self._events[-max(1, min(max_items, LEARNING_MAX_EVENTS)) :]
            lines = [json.dumps(item, ensure_ascii=False) for item in items]
        return "\n".join(lines)

    async def stats(self) -> Dict[str, int]:
        async with self._lock:
            total = len(self._events)
            open_count = sum(1 for item in self._events if str(item.get("status", "")) == "open")
            corrected = total - open_count
        return {"total": total, "open": open_count, "corrected": corrected}


learning_store = LearningLoopStore()
