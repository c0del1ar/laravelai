from collections import Counter
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

import httpx

from .config import (
    CONTEXT_MAX_PAGES,
    CONTEXT_PAGE_CONTENT_CHARS,
    RAG_CHUNK_TOP_K,
    RAG_CONTEXT_CHUNKS,
    RAG_MAX_CHUNKS_PER_PAGE,
    SEARCH_API_KEY,
    SEARCH_API_URL,
)
from .html_utils import normalize_path, tokenize_for_search
from .knowledge_base import kb
from .nlp import normalize_text, query_terms


def url_path(url: str) -> str:
    value = url.strip().rstrip("/")
    return (urlparse(value).path.rstrip("/") or "/") if value.startswith("http") else (value or "/")


async def search_website(query: str) -> List[Dict[str, Any]]:
    if not SEARCH_API_URL:
        return []
    headers = {"X-Search-Key": SEARCH_API_KEY} if SEARCH_API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(SEARCH_API_URL, params={"q": query}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("items", []) if isinstance(data, dict) else []
    except Exception:
        return []


def merge_search_items(search_batches: List[List[Dict[str, Any]]], max_items: int = 24) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for batch in search_batches:
        for item in batch:
            if not isinstance(item, dict):
                continue
            raw_url = str(item.get("url", "")).strip()
            if not raw_url:
                continue
            key = url_path(raw_url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            merged.append(item)
            if len(merged) >= max_items:
                return merged

    return merged


def summarize_form_specs(forms: List[Dict[str, Any]], max_forms: int = 2, max_fields: int = 8) -> str:
    if not forms:
        return ""

    blocks: List[str] = []
    for form in forms[:max_forms]:
        if not isinstance(form, dict):
            continue
        method = str(form.get("method", "get")).upper()
        action = str(form.get("action", "")).strip() or "(same page)"
        fields = form.get("fields", [])
        fields = fields if isinstance(fields, list) else []
        field_parts: List[str] = []

        for field in fields[:max_fields]:
            if not isinstance(field, dict):
                continue
            key = str(field.get("key", "")).strip()
            label = str(field.get("label", "")).strip()
            field_type = str(field.get("type", "text")).strip() or "text"
            required = bool(field.get("required", False))
            placeholder = str(field.get("placeholder", "")).strip()

            text = f"{label or key} [{field_type}]"
            if required:
                text += " required"
            if placeholder:
                text += f" placeholder={placeholder}"
            field_parts.append(text)

        buttons = form.get("buttons", [])
        buttons = [str(v).strip() for v in buttons if str(v).strip()]

        block = f"Form {method} {action}; fields: " + "; ".join(field_parts)
        if buttons:
            block += f"; buttons: {', '.join(buttons[:4])}"
        blocks.append(block)

    return " | ".join(blocks)


def build_context_for_groq(query: str, search_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    context_pages: List[Dict[str, Any]] = []
    seen_entries: Set[str] = set()
    chunks_per_path: Counter = Counter()

    def _entry_key(entry: Dict[str, Any]) -> str:
        return normalize_text(
            f"{entry.get('url', '')}|{entry.get('title', '')}|{entry.get('content', '')[:220]}|{entry.get('source', '')}"
        )

    def _safe_path_from_url(raw_url: str) -> str:
        value = raw_url.strip()
        if not value:
            return "/"
        if value.startswith("http"):
            return normalize_path(urlparse(value).path)
        return normalize_path(value)

    def _add_entry(*, title: str, url: str, summary: str, content: str, source: str) -> bool:
        if len(context_pages) >= CONTEXT_MAX_PAGES:
            return False
        clean_entry = {
            "title": str(title or "").strip(),
            "url": str(url or "").strip(),
            "summary": str(summary or "").strip(),
            "content": str(content or "").strip()[:CONTEXT_PAGE_CONTENT_CHARS],
            "source": str(source or "").strip(),
        }
        if not any(clean_entry.get(k) for k in ["title", "url", "summary", "content"]):
            return False
        key = _entry_key(clean_entry)
        if key in seen_entries:
            return False
        seen_entries.add(key)
        context_pages.append(clean_entry)
        return True

    search_by_path: Dict[str, Dict[str, Any]] = {}
    for item in search_items:
        if not isinstance(item, dict):
            continue
        path = _safe_path_from_url(str(item.get("url", "")))
        if path not in search_by_path:
            search_by_path[path] = item

    chunk_results = kb.search_relevant_chunks(query, top_k=max(RAG_CHUNK_TOP_K, CONTEXT_MAX_PAGES * 3))
    for chunk in chunk_results:
        path = normalize_path(str(chunk.get("path", "")))
        if chunks_per_path[path] >= RAG_MAX_CHUNKS_PER_PAGE:
            continue

        search_item = search_by_path.get(path, {})
        title = str(chunk.get("title", "")).strip() or str(search_item.get("title", "")).strip()
        raw_url = str(chunk.get("url", "")).strip() or str(search_item.get("url", "")).strip()
        summary = str(search_item.get("summary", "")).strip()
        content = str(chunk.get("content", "")).strip()

        if _add_entry(title=title, url=raw_url, summary=summary, content=content, source="crawl-chunk"):
            chunks_per_path[path] += 1
        if len(context_pages) >= min(CONTEXT_MAX_PAGES, RAG_CONTEXT_CHUNKS):
            break

    for item in search_items[: max(CONTEXT_MAX_PAGES * 2, 10)]:
        if not isinstance(item, dict):
            continue
        raw_url = str(item.get("url", "")).strip()
        path = _safe_path_from_url(raw_url)
        page = kb.get_page(path)
        page_form = summarize_form_specs(page.forms) if page else ""
        page_content = page.content if page else str(item.get("summary", "")).strip()
        if page_form:
            page_content = (page_content + "\n\nForm spec: " + page_form).strip()
        _add_entry(
            title=str(item.get("title", "")).strip(),
            url=raw_url,
            summary=str(item.get("summary", "")).strip(),
            content=page_content,
            source="search+crawl" if page else "search",
        )
        if len(context_pages) >= CONTEXT_MAX_PAGES:
            break

    if len(context_pages) < CONTEXT_MAX_PAGES:
        kb_results = kb.search_relevant(query, top_k=max(CONTEXT_MAX_PAGES * 2, 10))
        for page in kb_results:
            page_form = summarize_form_specs(page.forms)
            content = page.content
            if page_form:
                content = (content + "\n\nForm spec: " + page_form).strip()
            _add_entry(
                title=page.title,
                url=page.public_url,
                summary="",
                content=content,
                source="crawl",
            )
            if len(context_pages) >= CONTEXT_MAX_PAGES:
                break

    return context_pages[:CONTEXT_MAX_PAGES]


def page_relevance_score(message: str, page: Dict[str, Any]) -> float:
    q_terms = query_terms(message)
    if not q_terms:
        return 0.0

    title_tokens = tokenize_for_search(str(page.get("title", "")))
    url_tokens = tokenize_for_search(str(page.get("url", "")).replace("/", " "))
    summary_tokens = tokenize_for_search(str(page.get("summary", "")))
    content_tokens = tokenize_for_search(str(page.get("content", "")))
    content_tf = Counter(content_tokens + summary_tokens)

    score = 0.0
    matched: Set[str] = set()
    for term in q_terms:
        if term in title_tokens:
            score += 3.0
            matched.add(term)
        if term in url_tokens:
            score += 2.4
            matched.add(term)
        tf = min(content_tf.get(term, 0), 6)
        if tf > 0:
            score += 1.2 * tf
            matched.add(term)

    score += 0.9 * len(matched)
    return score


def has_context_relevance(message: str, context_pages: List[Dict[str, Any]]) -> bool:
    if not context_pages:
        return False
    if not query_terms(message):
        return False

    best_score = 0.0
    strong_hits = 0
    for page in context_pages:
        score = page_relevance_score(message, page)
        if score >= 3.0:
            strong_hits += 1
        if score > best_score:
            best_score = score

    return best_score >= 4.5 or (best_score >= 3.0 and strong_hits >= 2)


def _fallback_best_url(context_pages: List[Dict[str, Any]], message: str) -> str:
    best_score = 0.0
    best_url = ""

    for page in context_pages:
        raw_url = str(page.get("url", "")).strip()
        if not raw_url:
            continue
        score = page_relevance_score(message, page)
        if score > best_score:
            best_score = score
            best_url = raw_url

    if best_score >= 4.5:
        return best_url

    for page in kb.search_relevant(message, top_k=4):
        score = page_relevance_score(
            message,
            {
                "title": page.title,
                "url": page.public_url,
                "summary": "",
                "content": page.content[:CONTEXT_PAGE_CONTENT_CHARS],
            },
        )
        if score > best_score:
            best_score = score
            best_url = page.public_url

    return best_url if best_score >= 5.0 else ""


def enrich_navigation_result(
    result: Dict[str, Any],
    context_pages: List[Dict[str, Any]],
    message: str,
) -> Dict[str, Any]:
    rec_url = str(result.get("recommended_url", "")).strip()
    relevant = has_context_relevance(message, context_pages)
    if rec_url and relevant:
        return result

    if rec_url and not relevant:
        result["recommended_url"] = ""
        result["recommended_type"] = "none"
        result["related_items"] = []

    fallback_url = _fallback_best_url(context_pages, message)
    if not fallback_url:
        return result

    result["recommended_url"] = fallback_url
    if str(result.get("recommended_type", "")).strip() in {"", "none"}:
        result["recommended_type"] = "page"
    result["reason"] = str(result.get("reason", "")).strip() or "Fallback to best matching page from search context."
    return result
