import asyncio
import time
from typing import Any, Dict, List, Tuple

import httpx

from .config import (
    SLO_ALERT_COOLDOWN_SECONDS,
    SLO_ALERT_ENABLED,
    SLO_ALERT_WEBHOOK_URL,
    SLO_CHAT_CONFIDENCE_THRESHOLD,
    SLO_CHAT_LATENCY_MS_THRESHOLD,
    SLO_HTTP_5XX_RATE_THRESHOLD,
    SLO_MIN_SAMPLE_SIZE,
)


class SloAlertMonitor:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._last_sent_at: Dict[str, float] = {}

    def _breaches(self, snapshot: Dict[str, Any]) -> List[Tuple[str, str]]:
        breaches: List[Tuple[str, str]] = []
        http = snapshot.get("http", {}) if isinstance(snapshot, dict) else {}
        chat = snapshot.get("chat", {}) if isinstance(snapshot, dict) else {}

        status_counts = http.get("status_counts", {}) if isinstance(http, dict) else {}
        total_http = sum(int(v) for v in status_counts.values()) if isinstance(status_counts, dict) else 0
        five_xx = sum(int(v) for k, v in status_counts.items() if str(k).startswith("5")) if isinstance(status_counts, dict) else 0
        if total_http >= max(1, SLO_MIN_SAMPLE_SIZE):
            err_rate = (five_xx / total_http) if total_http else 0.0
            if err_rate > SLO_HTTP_5XX_RATE_THRESHOLD:
                breaches.append(("http_5xx_rate", f"HTTP 5xx rate {err_rate:.3f} > {SLO_HTTP_5XX_RATE_THRESHOLD:.3f}"))

        latency_samples = int(chat.get("latency_samples", 0) or 0) if isinstance(chat, dict) else 0
        latency_avg = float(chat.get("latency_ms_avg", 0.0) or 0.0) if isinstance(chat, dict) else 0.0
        confidence_avg = float(chat.get("confidence_avg", 0.0) or 0.0) if isinstance(chat, dict) else 0.0
        if latency_samples >= max(1, SLO_MIN_SAMPLE_SIZE) and latency_avg > SLO_CHAT_LATENCY_MS_THRESHOLD:
            breaches.append(("chat_latency", f"Chat latency avg {latency_avg:.1f}ms > {SLO_CHAT_LATENCY_MS_THRESHOLD:.1f}ms"))
        if latency_samples >= max(1, SLO_MIN_SAMPLE_SIZE) and confidence_avg < SLO_CHAT_CONFIDENCE_THRESHOLD:
            breaches.append(("chat_confidence", f"Chat confidence avg {confidence_avg:.3f} < {SLO_CHAT_CONFIDENCE_THRESHOLD:.3f}"))
        return breaches

    async def _send_alert(self, key: str, message: str):
        if not SLO_ALERT_WEBHOOK_URL:
            return
        payload = {
            "alert_key": key,
            "message": message,
            "ts": int(time.time()),
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            await client.post(SLO_ALERT_WEBHOOK_URL, json=payload)

    async def evaluate(self, snapshot: Dict[str, Any]):
        if not SLO_ALERT_ENABLED:
            return
        breaches = self._breaches(snapshot)
        if not breaches:
            return

        now = time.time()
        async with self._lock:
            for key, msg in breaches:
                last = float(self._last_sent_at.get(key, 0.0))
                if (now - last) < max(30, SLO_ALERT_COOLDOWN_SECONDS):
                    continue
                try:
                    await self._send_alert(key, msg)
                    self._last_sent_at[key] = now
                except Exception:
                    continue


slo_alert_monitor = SloAlertMonitor()
