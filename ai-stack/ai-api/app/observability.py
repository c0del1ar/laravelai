import asyncio
import time
from collections import Counter, deque
from typing import Any, Deque, Dict, Tuple


class Observability:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._http_counts: Counter = Counter()
        self._http_status: Counter = Counter()
        self._http_latency_ms: Deque[float] = deque(maxlen=500)
        self._chat_counts: Counter = Counter()
        self._chat_failures: Counter = Counter()
        self._chat_intents: Counter = Counter()
        self._chat_variants: Counter = Counter()
        self._chat_flags: Counter = Counter()
        self._chat_latency_ms: Deque[float] = deque(maxlen=500)
        self._chat_confidence: Deque[float] = deque(maxlen=500)
        self._prefix_gate_actions: Counter = Counter()
        self._last_errors: Deque[Dict[str, Any]] = deque(maxlen=40)
        self._started_at = time.time()

    async def record_http(self, method: str, path: str, status_code: int, latency_ms: float):
        async with self._lock:
            key = f"{method.upper()} {path}"
            self._http_counts[key] += 1
            self._http_status[str(status_code)] += 1
            self._http_latency_ms.append(max(0.0, float(latency_ms)))

    async def record_chat(
        self,
        *,
        channel: str,
        success: bool,
        latency_ms: float,
        confidence: float,
        context_pages: int,
        reason: str = "",
        intent_mode: str = "",
        experiment_variant: str = "",
        low_confidence: bool = False,
        handoff: bool = False,
        cache_hit: bool = False,
        grounded: bool = True,
    ):
        async with self._lock:
            self._chat_counts[channel] += 1
            if not success:
                self._chat_failures[channel] += 1
            if intent_mode:
                self._chat_intents[intent_mode] += 1
            if experiment_variant:
                self._chat_variants[experiment_variant] += 1
            if low_confidence:
                self._chat_flags["low_confidence"] += 1
            if handoff:
                self._chat_flags["handoff"] += 1
            if cache_hit:
                self._chat_flags["cache_hit"] += 1
            if not grounded:
                self._chat_flags["ungrounded"] += 1
            self._chat_latency_ms.append(max(0.0, float(latency_ms)))
            self._chat_confidence.append(max(0.0, min(1.0, float(confidence))))
            if not success or reason:
                self._last_errors.append(
                    {
                        "ts": int(time.time()),
                        "channel": channel,
                        "success": success,
                        "reason": str(reason)[:280],
                        "context_pages": int(context_pages),
                    }
                )

    async def record_prefix_gate(self, action: str):
        async with self._lock:
            key = str(action or "").strip() or "unknown"
            self._prefix_gate_actions[key] += 1

    async def snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            uptime_sec = int(max(0.0, time.time() - self._started_at))
            http_avg = (sum(self._http_latency_ms) / len(self._http_latency_ms)) if self._http_latency_ms else 0.0
            chat_avg = (sum(self._chat_latency_ms) / len(self._chat_latency_ms)) if self._chat_latency_ms else 0.0
            conf_avg = (sum(self._chat_confidence) / len(self._chat_confidence)) if self._chat_confidence else 0.0
            return {
                "uptime_sec": uptime_sec,
                "http": {
                    "total_by_route": dict(self._http_counts),
                    "status_counts": dict(self._http_status),
                    "latency_ms_avg": round(http_avg, 2),
                    "latency_samples": len(self._http_latency_ms),
                },
                "chat": {
                    "total_by_channel": dict(self._chat_counts),
                    "failures_by_channel": dict(self._chat_failures),
                    "intent_counts": dict(self._chat_intents),
                    "experiment_variants": dict(self._chat_variants),
                    "flags": dict(self._chat_flags),
                    "prefix_gate_actions": dict(self._prefix_gate_actions),
                    "latency_ms_avg": round(chat_avg, 2),
                    "confidence_avg": round(conf_avg, 3),
                    "latency_samples": len(self._chat_latency_ms),
                    "last_events": list(self._last_errors),
                },
            }


observability = Observability()
