import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query, Request

from .chat_service import (
    build_models_response,
    build_openai_chat_completion,
    extract_openclaw_payload,
    generate_chat_response,
    present_ai_result,
    require_bearer_auth_if_configured,
)
from .config import OPENCLAW_WEBHOOK_KEY
from .knowledge_base import kb
from .nlp import build_search_queries, detect_language, is_tutorial_intent
from .retrieval import build_context_for_groq, merge_search_items, search_website
from .schemas import ChatRequest
from .tools_manifest import find_relevant_tool_manifests


@asynccontextmanager
async def lifespan(app: FastAPI):
    kb.load_cache()
    asyncio.create_task(kb.force_crawl())
    yield


app = FastAPI(title="Website AI API", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pages_crawled": kb.page_count,
        "chunks_indexed": kb.chunk_count,
        "catalog_items": kb.catalog_count,
        "crawl_stale": kb.is_stale,
    }


@app.post("/admin/recrawl")
async def recrawl():
    asyncio.create_task(kb.force_crawl())
    return {"status": "crawl started"}


@app.get("/admin/rag/debug")
async def rag_debug(q: str = Query(..., min_length=1, max_length=300)):
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q is required")

    search_queries = build_search_queries(query, [])
    search_batches = await asyncio.gather(*(search_website(item) for item in search_queries[:3]))
    search_items = merge_search_items(search_batches)
    context_pages = build_context_for_groq(search_queries[0], search_items)
    chunk_hits = kb.search_relevant_chunks(search_queries[0], top_k=8)
    tutorial_mode = is_tutorial_intent(query)
    tool_manifest_hits = await find_relevant_tool_manifests(query, top_k=5) if tutorial_mode else []
    page_hits = [{"path": page.path, "url": page.public_url, "title": page.title} for page in kb.search_relevant(search_queries[0], top_k=8)]

    return {
        "query": query,
        "tutorial_mode": tutorial_mode,
        "search_queries": search_queries,
        "search_items": search_items[:8],
        "context_pages": context_pages,
        "chunk_hits": chunk_hits,
        "tool_manifest_hits": tool_manifest_hits,
        "page_hits": page_hits,
        "catalog_preview": kb.get_catalog(max_items=20),
    }


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    ai_result = await generate_chat_response(req.message, req.history)
    language = detect_language(req.message, req.history)
    return present_ai_result(ai_result, language)


@app.get("/v1/models")
async def openai_models(request: Request):
    require_bearer_auth_if_configured(request)
    return build_models_response()


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request, payload: Dict[str, Any]):
    require_bearer_auth_if_configured(request)
    return await build_openai_chat_completion(payload)


@app.post("/v1/openclaw")
async def openclaw_chat(request: Request, payload: Dict[str, Any]):
    if OPENCLAW_WEBHOOK_KEY:
        provided_key = request.headers.get("x-openclaw-key", "")
        if not provided_key or provided_key != OPENCLAW_WEBHOOK_KEY:
            raise HTTPException(status_code=403, detail="Forbidden")

    data = extract_openclaw_payload(payload)
    message = str(data["message"]).strip()
    if not message:
        raise HTTPException(status_code=422, detail="Invalid payload: message is required")

    ai_result = await generate_chat_response(message, data["history"])
    language = detect_language(message, data["history"])
    presented = present_ai_result(ai_result, language)
    reply = str(presented.get("answer", "")).strip()

    return {
        "ok": True,
        "reply": reply,
        "text": reply,
        "message": reply,
        "response": reply,
        "ai": presented,
        "user_id": data["user_id"],
    }
