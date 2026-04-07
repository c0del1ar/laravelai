import asyncio
import logging
from typing import Any, Dict, List, Tuple

import httpx

from .config import (
    GROQ_API_KEY,
    GROQ_FALLBACK_MODELS,
    GROQ_MODEL,
    GROQ_RETRY_BASE_DELAY_MS,
    GROQ_RETRY_MAX_ATTEMPTS,
)


logger = logging.getLogger("ai_fastapi")
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


def _resolve_model_sequence(preferred_model: str) -> List[str]:
    seq: List[str] = []
    first = preferred_model.strip() if preferred_model else GROQ_MODEL.strip()
    if first:
        seq.append(first)
    for model in GROQ_FALLBACK_MODELS:
        if model not in seq:
            seq.append(model)
    return seq or [GROQ_MODEL]


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429, 500, 502, 503, 504}


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ReadError, httpx.WriteError, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return _is_retryable_status(exc.response.status_code if exc.response is not None else 0)
    return False


async def _post_once(payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GROQ_CHAT_COMPLETIONS_URL,
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def post_chat_completion(
    *,
    messages: List[Dict[str, str]],
    temperature: float,
    response_format: Dict[str, Any],
    preferred_model: str,
) -> Tuple[Dict[str, Any], str]:
    """
    Returns (response_json, model_used).
    Uses model fallback and bounded retry with exponential backoff.
    """
    last_exc: Exception | None = None
    models = _resolve_model_sequence(preferred_model)
    max_attempts = max(1, GROQ_RETRY_MAX_ATTEMPTS)
    base_delay = max(50, GROQ_RETRY_BASE_DELAY_MS) / 1000.0

    for model in models:
        for attempt in range(1, max_attempts + 1):
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
            }
            try:
                result = await _post_once(payload)
                return result, model
            except Exception as exc:
                last_exc = exc
                retryable = _is_retryable_exception(exc)
                if not retryable:
                    break
                if attempt >= max_attempts:
                    break
                delay = base_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
        if isinstance(last_exc, httpx.HTTPStatusError) and last_exc.response is not None:
            status_code = last_exc.response.status_code
            if status_code in {400, 401, 403, 404}:
                continue
        elif isinstance(last_exc, Exception):
            logger.warning("Groq model attempt failed for %s: %s", model, type(last_exc).__name__)

    assert last_exc is not None
    raise last_exc
