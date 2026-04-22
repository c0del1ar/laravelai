import asyncio
import logging
from typing import Any, Dict, List, Tuple

import httpx

from .config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    LLM_DEFAULT_MODEL,
    LLM_FALLBACK_MODELS,
    LLM_PROVIDER,
    LLM_RETRY_BASE_DELAY_MS,
    LLM_RETRY_MAX_ATTEMPTS,
    OPENAI_BASE_URL,
)
from .openai_auth import get_openai_auth_headers, get_openai_auth_setup_error


logger = logging.getLogger("ai_fastapi")


def _chat_completions_url() -> str:
    provider = LLM_PROVIDER.strip().lower()
    if provider == "openai":
        return f"{OPENAI_BASE_URL}/chat/completions"
    if provider == "groq":
        return f"{GROQ_BASE_URL}/chat/completions"
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}")


async def _build_headers() -> Dict[str, str]:
    provider = LLM_PROVIDER.strip().lower()
    if provider == "openai":
        headers = await get_openai_auth_headers()
    elif provider == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not configured")
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}")

    headers["Content-Type"] = "application/json"
    return headers


def get_llm_auth_setup_error() -> str:
    provider = LLM_PROVIDER.strip().lower()
    if provider == "openai":
        return get_openai_auth_setup_error()
    if provider == "groq":
        return "" if GROQ_API_KEY else "GROQ_API_KEY is not configured"
    return f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}"


def _resolve_model_sequence(preferred_model: str) -> List[str]:
    seq: List[str] = []
    first = preferred_model.strip() if preferred_model else LLM_DEFAULT_MODEL.strip()
    if first:
        seq.append(first)
    for model in LLM_FALLBACK_MODELS:
        if model not in seq:
            seq.append(model)
    return seq or [LLM_DEFAULT_MODEL]


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429, 500, 502, 503, 504}


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ReadError, httpx.WriteError, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return _is_retryable_status(exc.response.status_code if exc.response is not None else 0)
    return False


async def _post_once(payload: Dict[str, Any]) -> Dict[str, Any]:
    headers = await _build_headers()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _chat_completions_url(),
            json=payload,
            headers=headers,
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
    max_attempts = max(1, LLM_RETRY_MAX_ATTEMPTS)
    base_delay = max(50, LLM_RETRY_BASE_DELAY_MS) / 1000.0

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
            logger.warning(
                "LLM model attempt failed for provider=%s model=%s error=%s",
                LLM_PROVIDER,
                model,
                type(last_exc).__name__,
            )

    assert last_exc is not None
    raise last_exc
