import hashlib
import math
from typing import List

import httpx

from .config import EMBEDDING_DIM, EMBEDDING_MODEL, EMBEDDING_PROVIDER, OPENAI_BASE_URL
from .html_utils import tokenize_for_search
from .openai_auth import get_openai_auth_headers


def _normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]


def _local_hash_embedding(text: str, dim: int) -> List[float]:
    tokens = tokenize_for_search(text)
    vec = [0.0] * dim
    if not tokens:
        return vec

    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % dim
        sign = -1.0 if (digest[2] & 1) else 1.0
        vec[idx] += sign
    return _normalize(vec)


async def _openai_embeddings(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    payload = {
        "model": EMBEDDING_MODEL,
        "input": texts,
    }
    headers = await get_openai_auth_headers()
    headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=40.0) as client:
        resp = await client.post(f"{OPENAI_BASE_URL}/embeddings", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    vectors: List[List[float]] = []
    for item in items:
        embedding = item.get("embedding", []) if isinstance(item, dict) else []
        if isinstance(embedding, list):
            vectors.append([float(v) for v in embedding])
    return vectors


async def embed_texts(texts: List[str]) -> List[List[float]]:
    clean = [str(t or "").strip() for t in texts]
    if not clean:
        return []

    provider = EMBEDDING_PROVIDER.strip().lower()
    if provider == "openai":
        try:
            return await _openai_embeddings(clean)
        except Exception:
            # graceful fallback to local embeddings
            pass

    dim = max(32, EMBEDDING_DIM)
    return [_local_hash_embedding(text, dim) for text in clean]


async def embed_text(text: str) -> List[float]:
    vectors = await embed_texts([text])
    return vectors[0] if vectors else []
