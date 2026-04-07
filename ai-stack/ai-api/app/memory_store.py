import asyncio
import json
import time
from typing import Dict, List

from .config import MEMORY_MAX_TURNS, MEMORY_STORE_PATH, MEMORY_TTL_SECONDS


class ConversationMemoryStore:
    def __init__(self):
        self._threads: Dict[str, List[Dict[str, str]]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _thread_key(user_id: str, channel: str) -> str:
        return f"{channel}:{user_id}".strip()

    def _prune_expired(self):
        if MEMORY_TTL_SECONDS <= 0:
            return
        now = time.time()
        cutoff = now - MEMORY_TTL_SECONDS
        to_delete = []
        for key, turns in self._threads.items():
            if not turns:
                to_delete.append(key)
                continue
            latest_ts = max(float(item.get("ts", 0) or 0) for item in turns)
            if latest_ts and latest_ts < cutoff:
                to_delete.append(key)
        for key in to_delete:
            self._threads.pop(key, None)

    async def load(self):
        async with self._lock:
            try:
                with open(MEMORY_STORE_PATH, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return
            raw_threads = payload.get("threads", {})
            if not isinstance(raw_threads, dict):
                return
            parsed: Dict[str, List[Dict[str, str]]] = {}
            for key, turns in raw_threads.items():
                if not isinstance(turns, list):
                    continue
                clean: List[Dict[str, str]] = []
                for item in turns:
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("role", "")).strip()
                    content = str(item.get("content", "")).strip()
                    if role not in {"user", "assistant"} or not content:
                        continue
                    clean.append(
                        {
                            "role": role,
                            "content": content[:2500],
                            "ts": float(item.get("ts", time.time()) or time.time()),
                        }
                    )
                if clean:
                    parsed[str(key)] = clean[-max(1, MEMORY_MAX_TURNS * 2) :]
            self._threads = parsed
            self._prune_expired()

    async def _save(self):
        payload = {"threads": self._threads}
        try:
            with open(MEMORY_STORE_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except Exception:
            pass

    async def get_history(self, user_id: str, channel: str) -> List[Dict[str, str]]:
        if not user_id:
            return []
        key = self._thread_key(user_id, channel)
        async with self._lock:
            self._prune_expired()
            turns = self._threads.get(key, [])
            return [
                {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
                for item in turns[-max(1, MEMORY_MAX_TURNS * 2) :]
            ]

    async def add_turn(self, user_id: str, channel: str, user_message: str, assistant_message: str):
        if not user_id:
            return
        key = self._thread_key(user_id, channel)
        async with self._lock:
            turns = self._threads.get(key, [])
            now = time.time()
            if user_message.strip():
                turns.append({"role": "user", "content": user_message.strip()[:2500], "ts": now})
            if assistant_message.strip():
                turns.append({"role": "assistant", "content": assistant_message.strip()[:2500], "ts": now})
            self._threads[key] = turns[-max(1, MEMORY_MAX_TURNS * 2) :]
            self._prune_expired()
            await self._save()

    async def merge_with_request_history(self, user_id: str, channel: str, request_history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        base = await self.get_history(user_id, channel)
        merged: List[Dict[str, str]] = []
        seen = set()
        for item in base + (request_history or []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            key = f"{role}:{content}"
            if key in seen:
                continue
            seen.add(key)
            merged.append({"role": role, "content": content})
        return merged[-max(1, MEMORY_MAX_TURNS * 2) :]

    async def stats(self) -> Dict[str, int]:
        async with self._lock:
            self._prune_expired()
            threads = len(self._threads)
            turns = sum(len(v) for v in self._threads.values())
            return {"threads": threads, "turns": turns}


memory_store = ConversationMemoryStore()
