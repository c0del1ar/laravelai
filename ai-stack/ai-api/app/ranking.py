import hashlib
import math
from collections import Counter
from typing import Dict, List, Set

from .html_utils import tokenize_for_search


def _hashed_embedding(text: str, dim: int = 128) -> List[float]:
    tokens = tokenize_for_search(text)
    if not tokens:
        return [0.0] * dim

    vec = [0.0] * dim
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % dim
        sign = -1.0 if (digest[2] & 1) else 1.0
        vec[idx] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def lexical_score(query_terms: List[str], doc: Dict[str, str]) -> float:
    title_tokens = tokenize_for_search(doc.get("title", ""))
    url_tokens = tokenize_for_search(doc.get("url", "").replace("/", " "))
    summary_tokens = tokenize_for_search(doc.get("summary", ""))
    content_tokens = tokenize_for_search(doc.get("content", ""))
    tf = Counter(content_tokens + summary_tokens)

    score = 0.0
    for term in query_terms:
        if term in title_tokens:
            score += 3.0
        if term in url_tokens:
            score += 2.2
        score += 1.1 * min(tf.get(term, 0), 8)
    return score


def semantic_score(query: str, doc: Dict[str, str]) -> float:
    doc_text = " ".join(
        [
            doc.get("title", ""),
            doc.get("summary", ""),
            doc.get("content", ""),
            doc.get("url", "").replace("/", " "),
        ]
    )
    qv = _hashed_embedding(query)
    dv = _hashed_embedding(doc_text)
    # Convert cosine [-1,1] to [0,1]
    return (_cosine(qv, dv) + 1.0) / 2.0


def hybrid_score(query: str, query_terms: List[str], doc: Dict[str, str]) -> float:
    lexical = lexical_score(query_terms, doc)
    semantic = semantic_score(query, doc)
    return (0.72 * lexical) + (0.28 * semantic * 10.0)


def _safe_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _intent_boost(intent_mode: str, doc: Dict[str, str]) -> float:
    text = " ".join(
        [
            str(doc.get("title", "")),
            str(doc.get("url", "")),
            str(doc.get("summary", "")),
            str(doc.get("source", "")),
        ]
    ).lower()
    if intent_mode == "pricing":
        return 0.85 if any(k in text for k in ["pricing", "harga", "plan", "paket"]) else 0.0
    if intent_mode == "contact":
        return 0.85 if any(k in text for k in ["contact", "kontak", "support", "hubungi"]) else 0.0
    if intent_mode == "tutorial":
        return 0.7 if any(k in text for k in ["tool", "checker", "panduan", "tutorial"]) else 0.0
    if intent_mode == "blog":
        return 0.65 if any(k in text for k in ["blog", "artikel", "post"]) else 0.0
    if intent_mode == "product":
        return 0.65 if any(k in text for k in ["product", "produk", "layanan"]) else 0.0
    if intent_mode == "feature":
        return 0.55 if any(k in text for k in ["fitur", "feature", "capability"]) else 0.0
    if intent_mode == "about":
        return 0.55 if any(k in text for k in ["about", "tentang", "aryakun"]) else 0.0
    if intent_mode == "troubleshoot":
        return 0.65 if any(k in text for k in ["error", "troubleshoot", "faq", "issue"]) else 0.0
    return 0.0


def rerank_entries(
    query: str,
    query_terms: List[str],
    entries: List[Dict[str, str]],
    top_k: int,
    intent_mode: str = "navigation",
) -> List[Dict[str, str]]:
    if not entries:
        return []

    ranked = []
    for entry in entries:
        hscore = hybrid_score(query, query_terms, entry)
        coverage = 0
        title_tokens = set(tokenize_for_search(entry.get("title", "")))
        content_tokens = set(tokenize_for_search(entry.get("content", "")))
        for term in set(query_terms):
            if term in title_tokens or term in content_tokens:
                coverage += 1
        source = entry.get("source", "")
        source_boost = 0.0
        if source == "tool-manifest":
            source_boost = 0.55
        elif source == "crawl-chunk":
            source_boost = 0.45
        elif source == "search+crawl":
            source_boost = 0.35
        elif source == "catalog-structured":
            source_boost = 0.25
        upstream_score = _safe_float(entry.get("score"))
        upstream_boost = min(1.2, upstream_score / 8.0)
        form_boost = 0.2 if "form" in str(entry.get("content", "")).lower() else 0.0
        final = hscore + (coverage * 0.6) + source_boost + upstream_boost + form_boost + _intent_boost(intent_mode, entry)
        payload = dict(entry)
        payload["_score"] = final
        ranked.append(payload)

    ranked.sort(key=lambda x: float(x.get("_score", 0.0)), reverse=True)
    return [dict(item) for item in ranked[:top_k]]


def confidence_from_entries(query_terms: List[str], entries: List[Dict[str, str]]) -> float:
    if not entries or not query_terms:
        return 0.18

    covered: Set[str] = set()
    top_scores: List[float] = []
    for entry in entries[:4]:
        text_tokens = set(
            tokenize_for_search(
                " ".join(
                    [
                        entry.get("title", ""),
                        entry.get("summary", ""),
                        entry.get("content", ""),
                    ]
                )
            )
        )
        for term in query_terms:
            if term in text_tokens:
                covered.add(term)
        top_scores.append(float(entry.get("_score", 0.0)))

    coverage_ratio = len(covered) / max(1, len(set(query_terms)))
    score_signal = sum(top_scores) / max(1, len(top_scores))
    normalized_signal = min(1.0, max(0.0, score_signal / 12.0))
    return max(0.0, min(0.99, (0.62 * coverage_ratio) + (0.38 * normalized_signal)))
