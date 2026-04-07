import asyncio
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

from .config import SEMANTIC_MIN_SCORE, SEMANTIC_TOP_K, VECTOR_DB_PATH
from .embeddings import embed_text, embed_texts


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def _ensure_db():
    parent = os.path.dirname(VECTOR_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(VECTOR_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vectors (
                chunk_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vectors_path ON vectors(path);")
        conn.commit()
    finally:
        conn.close()


class VectorStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        _ensure_db()

    async def reindex_chunks(self, chunks: List[Dict[str, str]]) -> int:
        rows = [dict(item) for item in chunks if isinstance(item, dict)]
        if not rows:
            return 0

        texts = []
        for row in rows:
            texts.append(
                " ".join(
                    [
                        str(row.get("title", "")),
                        str(row.get("path", "")),
                        str(row.get("content", "")),
                    ]
                ).strip()
            )

        vectors = await embed_texts(texts)
        if not vectors:
            return 0

        async with self._lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            try:
                now = asyncio.get_running_loop().time()
                conn.execute("DELETE FROM vectors;")
                for row, vector in zip(rows, vectors):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO vectors
                        (chunk_id, path, url, title, content, embedding, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(row.get("chunk_id", "")),
                            str(row.get("path", "")),
                            str(row.get("url", "")),
                            str(row.get("title", "")),
                            str(row.get("content", "")),
                            json.dumps(vector, ensure_ascii=False),
                            float(now),
                        ),
                    )
                conn.commit()
                return len(rows)
            finally:
                conn.close()

    async def search(
        self,
        query: str,
        top_k: int = SEMANTIC_TOP_K,
        min_score: float = SEMANTIC_MIN_SCORE,
    ) -> List[Dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []

        query_vec = await embed_text(q)
        if not query_vec:
            return []

        async with self._lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            try:
                cursor = conn.execute("SELECT chunk_id, path, url, title, content, embedding FROM vectors")
                rows = cursor.fetchall()
            finally:
                conn.close()

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for chunk_id, path, url, title, content, embedding_json in rows:
            try:
                vec = json.loads(str(embedding_json))
                if not isinstance(vec, list):
                    continue
                vec = [float(v) for v in vec]
            except Exception:
                continue
            score = _cosine(query_vec, vec)
            if score < min_score:
                continue
            scored.append(
                (
                    score,
                    {
                        "chunk_id": str(chunk_id),
                        "path": str(path),
                        "url": str(url),
                        "title": str(title),
                        "content": str(content),
                        "score": f"{score:.4f}",
                        "source": "vector-semantic",
                    },
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[: max(1, top_k)]]

    async def stats(self) -> Dict[str, Any]:
        async with self._lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            try:
                row = conn.execute("SELECT COUNT(1) FROM vectors").fetchone()
                count = int(row[0]) if row else 0
            finally:
                conn.close()
        return {"db_path": VECTOR_DB_PATH, "rows": count}


vector_store = VectorStore()
