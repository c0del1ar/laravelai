import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from .chat_service import (
    build_models_response,
    build_openai_chat_completion,
    evaluate_openclaw_prefix_gate,
    extract_openclaw_payload,
    generate_chat_response,
    present_ai_result,
    require_bearer_auth_if_configured,
    resolve_sender_id,
)
from .config import INTERNAL_INDEX_KEY, OPENCLAW_WEBHOOK_KEY
from .handoff_state import handoff_state
from .html_utils import normalize_path
from .index_event_queue import index_event_queue
from .intent_router import classify_intent_profile, expand_queries_for_intent
from .knowledge_base import kb
from .learning_loop import learning_store
from .memory_store import memory_store
from .observability import observability
from .prefix_gate_store import prefix_gate_store
from .nlp import detect_language
from .response_cache import response_cache
from .retrieval import build_context_for_groq, merge_search_items, search_website
from .schemas import ChatRequest, FeedbackRequest, IndexPathsRequest, LearningCorrectionRequest
from .site_catalog import fetch_site_catalog, merge_site_catalogs, rank_catalog_items, site_catalog_cache_stats
from .slo_alerts import slo_alert_monitor
from .tools_manifest import find_relevant_tool_manifests
from .vector_store import vector_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    kb.load_cache()
    await memory_store.load()
    await learning_store.load()
    await prefix_gate_store.load()
    await response_cache.load()
    await handoff_state.load()
    asyncio.create_task(kb.rebuild_vector_index())
    asyncio.create_task(kb.force_crawl())
    yield


app = FastAPI(title="Website AI API", lifespan=lifespan)


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        await observability.record_http(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            latency_ms=elapsed_ms,
        )
        if not request.url.path.startswith("/admin"):
            snapshot = await observability.snapshot()
            await slo_alert_monitor.evaluate(snapshot)


@app.get("/health")
async def health():
    vector_stats = await vector_store.stats()
    return {
        "status": "ok",
        "pages_crawled": kb.page_count,
        "chunks_indexed": kb.chunk_count,
        "catalog_items": kb.catalog_count,
        "crawl_stale": kb.is_stale,
        "memory": await memory_store.stats(),
        "learning": await learning_store.stats(),
        "response_cache": await response_cache.stats(),
        "handoff": await handoff_state.stats(),
        "index_queue": await index_event_queue.stats(),
        "structured_catalog": site_catalog_cache_stats(),
        "vector": vector_stats,
    }


@app.post("/admin/recrawl")
async def recrawl():
    asyncio.create_task(kb.force_crawl())
    return {"status": "crawl started"}


def _require_index_key(request: Request):
    if not INTERNAL_INDEX_KEY:
        return
    provided = str(request.headers.get("x-index-key", "")).strip()
    if not provided or provided != INTERNAL_INDEX_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/admin/index/paths")
@app.post("/admin/index/changed")
async def index_paths(payload: IndexPathsRequest, request: Request):
    _require_index_key(request)
    normalized = [normalize_path(v) for v in payload.paths if str(v).strip()]
    for url in payload.urls:
        raw = str(url).strip()
        if not raw:
            continue
        if raw.startswith("http://") or raw.startswith("https://"):
            normalized.append(normalize_path(urlparse(raw).path))
        else:
            normalized.append(normalize_path(raw))

    result = await kb.refresh_paths(normalized)
    return {"ok": True, **result}


@app.post("/admin/index/events")
async def index_events(payload: IndexPathsRequest, request: Request):
    _require_index_key(request)
    normalized = [normalize_path(v) for v in payload.paths if str(v).strip()]
    for url in payload.urls:
        raw = str(url).strip()
        if not raw:
            continue
        if raw.startswith("http://") or raw.startswith("https://"):
            normalized.append(normalize_path(urlparse(raw).path))
        else:
            normalized.append(normalize_path(raw))
    queued = await index_event_queue.enqueue(normalized)
    return {"ok": True, **queued}


@app.get("/admin/metrics")
async def metrics():
    snapshot = await observability.snapshot()
    snapshot["memory"] = await memory_store.stats()
    snapshot["learning"] = await learning_store.stats()
    snapshot["prefix_gate"] = await prefix_gate_store.stats()
    snapshot["response_cache"] = await response_cache.stats()
    snapshot["handoff"] = await handoff_state.stats()
    snapshot["index_queue"] = await index_event_queue.stats()
    snapshot["vector"] = await vector_store.stats()
    snapshot["structured_catalog"] = site_catalog_cache_stats()
    snapshot["kb"] = {
        "pages": kb.page_count,
        "chunks": kb.chunk_count,
        "catalog": kb.catalog_count,
        "is_stale": kb.is_stale,
    }
    return snapshot


@app.get("/admin/rag/debug")
async def rag_debug(q: str = Query(..., min_length=1, max_length=300)):
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q is required")

    profile = classify_intent_profile(query)
    intent_mode = str(profile.get("intent_mode", "navigation"))
    tutorial_mode = bool(profile.get("tutorial_mode", False))
    search_queries = expand_queries_for_intent(query, [], profile)
    search_batches = await asyncio.gather(*(search_website(item) for item in search_queries[:3]))
    search_items = merge_search_items(search_batches)
    semantic_chunks = await kb.search_semantic_chunks(search_queries[0], top_k=8)
    local_catalog = kb.get_catalog(max_items=120)
    remote_catalog = await fetch_site_catalog()
    merged_catalog = merge_site_catalogs(local_catalog, remote_catalog, max_items=180)
    catalog_candidates = rank_catalog_items(search_queries[0], merged_catalog, intent_mode=intent_mode, top_k=24)
    context_pages = build_context_for_groq(
        search_queries[0],
        search_items,
        semantic_chunks=semantic_chunks,
        intent_mode=intent_mode,
        catalog_items=catalog_candidates,
    )
    chunk_hits = kb.search_relevant_chunks(search_queries[0], top_k=8)
    tool_manifest_hits = await find_relevant_tool_manifests(query, top_k=5) if tutorial_mode else []
    page_hits = [{"path": page.path, "url": page.public_url, "title": page.title} for page in kb.search_relevant(search_queries[0], top_k=8)]

    return {
        "query": query,
        "intent_profile": profile,
        "tutorial_mode": tutorial_mode,
        "search_queries": search_queries,
        "search_items": search_items[:8],
        "context_pages": context_pages,
        "semantic_chunk_hits": semantic_chunks,
        "chunk_hits": chunk_hits,
        "tool_manifest_hits": tool_manifest_hits,
        "page_hits": page_hits,
        "catalog_remote_count": len(remote_catalog),
        "catalog_preview": merged_catalog[:20],
        "catalog_candidates": catalog_candidates[:20],
    }


@app.get("/admin/learning/failures")
async def learning_failures(request: Request, limit: int = Query(100, ge=1, le=500)):
    _require_index_key(request)
    return {"items": await learning_store.list_open(limit=limit)}


@app.post("/admin/learning/corrections")
async def learning_corrections(payload: LearningCorrectionRequest, request: Request):
    _require_index_key(request)
    ok = await learning_store.apply_correction(
        payload.event_id,
        payload.corrected_answer,
        payload.corrected_url,
        payload.tags,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="event_id not found")
    return {"ok": True}


@app.get("/admin/learning/export")
async def learning_export(request: Request, limit: int = Query(1000, ge=1, le=5000)):
    _require_index_key(request)
    data = await learning_store.export_jsonl(max_items=limit)
    return PlainTextResponse(data, media_type="application/x-ndjson")


@app.get("/admin/ops", response_class=HTMLResponse)
async def ops_page():
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>AI Ops Panel</title>
  <style>
    body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 24px; background: #0f172a; color: #e2e8f0; }
    h1 { margin: 0 0 12px; }
    .row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
    button { padding: 8px 12px; border: 0; border-radius: 8px; background: #334155; color: #fff; cursor: pointer; }
    textarea, input { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #334155; background: #020617; color: #e2e8f0; }
    pre { background: #020617; padding: 12px; border-radius: 8px; overflow: auto; border: 1px solid #334155; max-height: 420px; }
    .card { background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 12px; margin-bottom: 14px; }
  </style>
</head>
<body>
  <h1>AI Ops Panel</h1>
  <div class="card">
    <div class="row">
      <button onclick="loadMetrics()">Refresh Metrics</button>
      <button onclick="triggerRecrawl()">Trigger Recrawl</button>
      <button onclick="loadFailures()">Load Learning Failures</button>
    </div>
    <label>X-Index-Key</label>
    <input id="indexKey" placeholder="paste internal index key"/>
  </div>
  <div class="card">
    <label>Incremental Paths (comma-separated)</label>
    <input id="paths" placeholder="/tools/noredirect,/pricing"/>
    <div class="row"><button onclick="triggerIndex()">Run Incremental Index</button></div>
  </div>
  <div class="card"><h3>Metrics</h3><pre id="metrics">-</pre></div>
  <div class="card"><h3>Learning Failures</h3><pre id="failures">-</pre></div>
  <script>
    async function loadMetrics(){
      const r = await fetch('/admin/metrics');
      const j = await r.json();
      document.getElementById('metrics').textContent = JSON.stringify(j, null, 2);
    }
    async function triggerRecrawl(){
      const r = await fetch('/admin/recrawl', { method:'POST' });
      alert('recrawl: '+r.status);
    }
    async function triggerIndex(){
      const key = document.getElementById('indexKey').value;
      const pathsRaw = document.getElementById('paths').value;
      const paths = pathsRaw.split(',').map(v=>v.trim()).filter(Boolean);
      const r = await fetch('/admin/index/changed', {
        method:'POST',
        headers:{'Content-Type':'application/json', 'X-Index-Key': key},
        body: JSON.stringify({paths})
      });
      const j = await r.json();
      alert(JSON.stringify(j));
    }
    async function loadFailures(){
      const key = document.getElementById('indexKey').value;
      const r = await fetch('/admin/learning/failures?limit=100', { headers: {'X-Index-Key': key} });
      const j = await r.json();
      document.getElementById('failures').textContent = JSON.stringify(j, null, 2);
    }
    loadMetrics();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    ai_result = await generate_chat_response(req.message, req.history, user_id=req.user_id, channel="web")
    language = detect_language(req.message, req.history)
    return present_ai_result(ai_result, language, channel="web")


@app.post("/v1/feedback")
async def feedback(payload: FeedbackRequest):
    channel = str(payload.channel or "web").strip() or "web"
    feedback_id = await learning_store.record_feedback(
        channel=channel[:24],
        user_id=str(payload.user_id or "").strip(),
        message=str(payload.message or "").strip(),
        answer=str(payload.answer or "").strip(),
        recommended_url=str(payload.recommended_url or "").strip(),
        reason=str(payload.reason or "").strip(),
        intent_mode=str(payload.intent_mode or "").strip(),
        rating=int(payload.rating),
        response_id=str(payload.response_id or "").strip(),
    )
    return {"ok": True, "feedback_id": feedback_id}


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
    sender_id = resolve_sender_id(payload, message, str(data["user_id"] or ""))
    gate = await evaluate_openclaw_prefix_gate(message, sender_id)
    gate_action = str(gate.get("action", "proceed")).strip()
    await observability.record_prefix_gate(gate_action)
    if gate_action == "reply":
        reply = str(gate.get("message", "")).strip()
        return {
            "ok": True,
            "reply": reply,
            "text": reply,
            "message": reply,
            "response": reply,
            "ai": {"answer": reply, "reason": "prefix-gate-reminder"},
            "user_id": data["user_id"],
            "prefix_gate": gate_action,
        }
    if gate_action in {"silent", "drop"}:
        return {
            "ok": True,
            "reply": "",
            "text": "",
            "message": "",
            "response": "",
            "ai": {"answer": "", "reason": "prefix-gate-silent"},
            "user_id": data["user_id"],
            "prefix_gate": gate_action,
        }
    message = str(gate.get("message", message)).strip()
    if not message:
        return {
            "ok": True,
            "reply": "",
            "text": "",
            "message": "",
            "response": "",
            "ai": {"answer": "", "reason": "prefix-gate-empty"},
            "user_id": data["user_id"],
            "prefix_gate": gate_action,
        }

    ai_result = await generate_chat_response(
        message,
        data["history"],
        user_id=str(data["user_id"] or "").strip() or None,
        channel="openclaw",
    )
    language = detect_language(message, data["history"])
    presented = present_ai_result(ai_result, language, channel="openclaw")
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
