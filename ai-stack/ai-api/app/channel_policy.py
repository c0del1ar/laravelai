import re
from typing import Any, Dict

from .config import (
    CHANNEL_POLICY_OPENAI_MAX_SENTENCES,
    CHANNEL_POLICY_OPENCLAW_MAX_SENTENCES,
    CHANNEL_POLICY_WEB_MAX_SENTENCES,
)


def _max_sentences(channel: str) -> int:
    if channel == "openclaw":
        return max(1, CHANNEL_POLICY_OPENCLAW_MAX_SENTENCES)
    if channel == "openai":
        return max(1, CHANNEL_POLICY_OPENAI_MAX_SENTENCES)
    return max(1, CHANNEL_POLICY_WEB_MAX_SENTENCES)


def _trim_sentences(text: str, max_sentences: int) -> str:
    value = str(text or "").strip()
    if not value:
        return value
    parts = re.split(r"(?<=[.!?])\s+", value)
    if len(parts) <= max_sentences:
        return value
    return " ".join(parts[:max_sentences]).strip()


def apply_channel_guardrails(result: Dict[str, Any], channel: str) -> Dict[str, Any]:
    payload = dict(result)
    payload["answer"] = _trim_sentences(str(payload.get("answer", "")), _max_sentences(channel))
    confidence = float(payload.get("confidence_score", 0.0) or 0.0)

    if channel == "openclaw":
        related = payload.get("related_items", [])
        if isinstance(related, list):
            payload["related_items"] = related[:1]
        sources = payload.get("sources", [])
        if isinstance(sources, list):
            payload["sources"] = sources[:1]
        if confidence < 0.45:
            payload["related_items"] = []
    elif channel == "openai":
        # OpenAI-compatible response should be plain and deterministic.
        payload["answer"] = payload["answer"].replace("\n\n", "\n").strip()
        if isinstance(payload.get("related_items"), list):
            payload["related_items"] = payload["related_items"][:1]
    else:
        # Web can carry richer navigation context.
        if isinstance(payload.get("related_items"), list):
            payload["related_items"] = payload["related_items"][:3]
        if isinstance(payload.get("sources"), list):
            payload["sources"] = payload["sources"][:3]

    if confidence < 0.36:
        payload["recommended_url"] = ""
        payload["recommended_type"] = "none"
        payload["related_items"] = []
    return payload
