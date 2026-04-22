from typing import Dict

from .config import OPENAI_API_KEY, OPENAI_AUTH_MODE, OPENAI_OAUTH_ACCESS_TOKEN


def get_openai_auth_setup_error() -> str:
    mode = OPENAI_AUTH_MODE.strip().lower()
    if mode == "api_key":
        return "" if OPENAI_API_KEY else "OPENAI_API_KEY is not configured"
    if mode == "oauth":
        if OPENAI_OAUTH_ACCESS_TOKEN:
            return ""
        return "OPENAI_OAUTH_ACCESS_TOKEN is not configured for OPENAI_AUTH_MODE=oauth"
    return "OPENAI_AUTH_MODE must be either 'api_key' or 'oauth'"


def _resolve_bearer_token() -> str:
    mode = OPENAI_AUTH_MODE.strip().lower()
    if mode == "api_key":
        token = OPENAI_API_KEY
    elif mode == "oauth":
        token = OPENAI_OAUTH_ACCESS_TOKEN
    else:
        token = ""

    if not token:
        raise RuntimeError(get_openai_auth_setup_error())
    return token


async def get_openai_auth_headers() -> Dict[str, str]:
    token = _resolve_bearer_token()
    return {"Authorization": f"Bearer {token}"}
