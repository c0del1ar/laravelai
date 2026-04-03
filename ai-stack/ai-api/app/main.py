import os
import json
import re
import time
import asyncio
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Set

import httpx
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────
SEARCH_API_URL = os.getenv("SEARCH_API_URL", "")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "")        # internal: http://aryakunid-laravel_franken-1:8000
SITE_PUBLIC_URL = os.getenv("SITE_PUBLIC_URL", "")    # public:   https://aryakun.id
CRAWL_TTL = int(os.getenv("CRAWL_TTL", str(60 * 60 * 6)))  # re-crawl every 6 hours
CRAWL_MAX_PAGES = int(os.getenv("CRAWL_MAX_PAGES", "60"))
CRAWL_TIMEOUT = int(os.getenv("CRAWL_TIMEOUT", "8"))


# ── HTML text extractor ───────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "nav", "footer", "head", "noscript", "svg", "button"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        return re.sub(r"\s+", " ", raw).strip()


def extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return ""


def extract_text_from_html(html: str, max_chars: int = 3000) -> str:
    parser = TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = parser.get_text()
    return text[:max_chars]


# ── Website Knowledge Base ────────────────────────────────────────────────────
class PageInfo:
    __slots__ = ("path", "public_url", "title", "content", "crawled_at")

    def __init__(self, path: str, public_url: str, title: str, content: str):
        self.path = path
        self.public_url = public_url
        self.title = title
        self.content = content
        self.crawled_at = time.time()


class WebsiteKnowledgeBase:
    def __init__(self):
        self._pages: Dict[str, PageInfo] = {}   # path → PageInfo
        self._crawled_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_stale(self) -> bool:
        return (time.time() - self._crawled_at) > CRAWL_TTL

    @property
    def page_count(self) -> int:
        return len(self._pages)

    def get_paths(self) -> Set[str]:
        return set(self._pages.keys())

    def get_page(self, path: str) -> Optional[PageInfo]:
        return self._pages.get(path.rstrip("/") or "/")

    def search_relevant(self, query: str, top_k: int = 4) -> List[PageInfo]:
        """Find most relevant pages based on keyword overlap with query."""
        terms = [t for t in normalize_text(query).split() if len(t) > 1]
        if not terms:
            return []

        scored: List[tuple] = []
        for page in self._pages.values():
            haystack = normalize_text(f"{page.title} {page.content}")
            score = 0
            for term in terms:
                if term in haystack:
                    score += 3
                if term in normalize_text(page.title):
                    score += 5
                if term in page.path:
                    score += 4
            if score > 0:
                scored.append((score, page))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]

    async def crawl(self):
        async with self._lock:
            if not self.is_stale:
                return
            await self._do_crawl()

    async def force_crawl(self):
        async with self._lock:
            await self._do_crawl()

    async def _do_crawl(self):
        if not SITE_BASE_URL:
            return

        base = SITE_BASE_URL.rstrip("/")
        public_base = (SITE_PUBLIC_URL or SITE_BASE_URL).rstrip("/")

        # Step 1: fetch sitemap
        paths = await self._fetch_sitemap_paths(base)
        if not paths:
            return

        # Step 2: crawl each page concurrently (max 8 at a time)
        sem = asyncio.Semaphore(8)
        tasks = [self._crawl_page(base, public_base, path, sem)
                 for path in list(paths)[:CRAWL_MAX_PAGES]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        new_pages: Dict[str, PageInfo] = {}
        for r in results:
            if isinstance(r, PageInfo):
                new_pages[r.path] = r

        self._pages = new_pages
        self._crawled_at = time.time()

    async def _fetch_sitemap_paths(self, base: str) -> Set[str]:
        paths: Set[str] = set()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base}/sitemap.xml")
                resp.raise_for_status()
                root = ET.fromstring(resp.text)

            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            for loc in root.findall(".//sm:loc", ns):
                url = (loc.text or "").strip().rstrip("/")
                if url:
                    path = urlparse(url).path.rstrip("/") or "/"
                    paths.add(path)

            # sitemap index
            for ref in root.findall("sm:sitemap/sm:loc", ns):
                child_url = (ref.text or "").strip()
                if not child_url:
                    continue
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        cr = await client.get(child_url)
                        cr.raise_for_status()
                        cr_root = ET.fromstring(cr.text)
                    for loc in cr_root.findall(".//sm:loc", ns):
                        url = (loc.text or "").strip().rstrip("/")
                        if url:
                            paths.add(urlparse(url).path.rstrip("/") or "/")
                except Exception:
                    continue
        except Exception:
            pass
        return paths

    async def _crawl_page(self, base: str, public_base: str, path: str, sem: asyncio.Semaphore) -> Optional["PageInfo"]:
        async with sem:
            try:
                url = base + path
                async with httpx.AsyncClient(timeout=CRAWL_TIMEOUT) as client:
                    resp = await client.get(url, headers={"Accept": "text/html"}, follow_redirects=True)
                    if resp.status_code != 200:
                        return None
                    html = resp.text

                title = extract_title(html)
                content = extract_text_from_html(html)

                if not content and not title:
                    return None

                return PageInfo(
                    path=path,
                    public_url=public_base + path,
                    title=title,
                    content=content,
                )
            except Exception:
                return None


# Global knowledge base instance
kb = WebsiteKnowledgeBase()


# ── App lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    # Crawl website at startup
    asyncio.create_task(kb.force_crawl())
    yield


app = FastAPI(title="Website AI API", lifespan=lifespan)


# ── Models ────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: List[Dict[str, Any]] = Field(default_factory=list)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pages_crawled": kb.page_count,
        "crawl_stale": kb.is_stale,
    }


@app.post("/admin/recrawl")
async def recrawl():
    asyncio.create_task(kb.force_crawl())
    return {"status": "crawl started"}


# ── Text helpers ──────────────────────────────────────────────────────────────
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s\-_/]", " ", text.lower())).strip()


INDONESIAN_MARKERS = [
    "apa", "bagaimana", "kenapa", "siapa", "kapan", "dimana", "di mana",
    "tolong", "bantu", "cari", "butuh", "ingin", "mau", "saya", "aku",
    "kamu", "ada", "jelaskan", "tentang", "harga", "pakai", "buat",
    "bisa", "gimana", "dong", "nih", "ya", "yang",
]
ENGLISH_MARKERS = [
    "what", "how", "why", "who", "when", "where", "please", "help",
    "find", "need", "want", "about", "explain", "price", "use", "for",
    "can", "could", "show", "article", "blog", "tool", "product",
]


def detect_language(message: str, history: Optional[List[Dict]] = None) -> str:
    samples = [message]
    if history:
        for item in history[-4:]:
            if isinstance(item, dict):
                samples.append(str(item.get("content", "")))
    text = f" {normalize_text(' '.join(samples))} "
    id_score = sum(1 for m in INDONESIAN_MARKERS if f" {m} " in text)
    en_score = sum(1 for m in ENGLISH_MARKERS if f" {m} " in text)
    return "id" if id_score >= en_score else "en"


def extract_core_query(message: str) -> str:
    q = normalize_text(message)
    noise_patterns = [
        r"\bdo you have\b", r"\byou have\b", r"\bhave you\b",
        r"\bdo you\b", r"\byou got\b", r"\bis there\b", r"\bare there\b",
        r"\bcan i get\b", r"\bcan i find\b", r"\bcan i see\b",
        r"\bcan you show\b", r"\bcan you find\b", r"\bcan you give\b",
        r"\bi am looking\b", r"\bi am searching\b",
        r"\bi need\b", r"\bi want\b", r"\bshow me\b", r"\bfind me\b",
        r"\blooking for\b", r"\bgive me\b",
        r"\bpost about\b", r"\bblog about\b", r"\barticle about\b",
        r"\bguide about\b", r"\btutorial about\b", r"\btool for\b",
        r"\bproduct for\b", r"\bpricing for\b",
        r"\barticle\b", r"\bpost\b", r"\bblog\b", r"\bguide\b",
        r"\btutorial\b", r"\bdocumentation\b", r"\bdocs\b",
        r"\bsomething about\b", r"\banything about\b",
        r"\binfo about\b", r"\binformation about\b",
        r"\brelated to\b", r"\bregarding\b",
        r"\bsomething\b", r"\banything\b", r"\bstuff\b",
        r"\binfo\b", r"\binformation\b",
        r"\babout\b", r"\bplease\b",
        r"\bthe\b", r"\bsome\b", r"\bany\b",
        r"\byou\b", r"\bhave\b", r"\bme\b", r"\bmy\b",
        r"\bdo\b", r"\bdoes\b", r"\bwhat\b", r"\bwhere\b",
        r"\bshow\b", r"\bfind\b", r"\bgive\b", r"\bneed\b",
        r"\bwant\b", r"\blooking\b", r"\bsearch\b",
        r"\bsaya ingin\b", r"\bsaya mau\b", r"\bsaya cari\b",
        r"\bsaya butuh\b", r"\bsaya perlu\b", r"\bsaya minta\b",
        r"\bcarikan\b", r"\btampilkan\b", r"\bberikan\b",
        r"\bada tidak\b", r"\bada gak\b", r"\bapakah ada\b",
        r"\bmengenai\b", r"\btentang\b", r"\bsoal\b", r"\bterkait\b",
        r"\btolong\b", r"\bmohon\b", r"\bbantu\b",
        r"\bsesuatu\b", r"\bhal\b", r"\bapapun\b",
        r"\bartikel\b", r"\bpanduan\b", r"\btulisan\b", r"\bkonten\b",
        r"\bada\b", r"\bapakah\b", r"\bapa\b",
    ]
    for pattern in noise_patterns:
        q = re.sub(pattern, " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q or normalize_text(message)


FOLLOW_UP_MARKERS = [
    "yang", "itu", "tadi", "ini", "lanjut", "lanjutin", "lebih", "lagi",
    "gratis", "free", "murah", "termurah", "indonesia", "english",
    "versi", "pakai", "gunakan", "bedanya", "compare", "comparison",
]


def build_search_query(message: str, history: List[Dict[str, Any]]) -> str:
    base_query = extract_core_query(message)
    normalized_message = normalize_text(message)

    # Only merge history for explicit follow-up words — not for standalone keywords
    is_follow_up = any(marker in normalized_message for marker in FOLLOW_UP_MARKERS)
    if not is_follow_up:
        return base_query

    prev_messages: List[str] = []
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if item.get("role") == "user" and item.get("content"):
            prev_messages.append(str(item["content"]))
        if len(prev_messages) >= 2:
            break

    if not prev_messages:
        return base_query

    seen: Set[str] = set()
    merged: List[str] = []
    for part in list(reversed(prev_messages)) + [base_query]:
        for term in normalize_text(part).split():
            if term and term not in seen:
                seen.add(term)
                merged.append(term)

    return " ".join(merged).strip() or base_query


# ── Owner profile ─────────────────────────────────────────────────────────────
OWNER_MARKERS = [
    "owner", "lord", "master", "creator", "founder", "maker", "boss",
    "pemilik", "tuan", "majikan", "pencipta", "pembuat", "siapa arya",
    "siapa owner", "siapa tuan", "siapa pemilik", "who is arya", "who is your owner",
]
OWNER_PROFILE = {
    "name": "Arya gege",
    "role": "owner and lord of Xiao-An",
    "traits": ["handsome", "brave", "charismatic", "confident"],
}


def is_owner_query(message: str) -> bool:
    q = normalize_text(message)
    return any(m in q for m in OWNER_MARKERS)


# ── External: search API ──────────────────────────────────────────────────────
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


# ── Context builder ───────────────────────────────────────────────────────────
def build_context_for_groq(
    query: str,
    search_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build rich context by combining:
    1. Search API results (structured: title, url, summary)
    2. Knowledge base page content (actual crawled text)
    """
    context_pages: List[Dict[str, Any]] = []
    seen_paths: Set[str] = set()

    # From search results first (most relevant)
    for item in search_items[:5]:
        url = str(item.get("url", ""))
        path = url if not url.startswith("http") else urlparse(url).path
        path = path.rstrip("/") or "/"

        page = kb.get_page(path)
        entry = {
            "title": item.get("title", ""),
            "url": url,
            "summary": item.get("summary", ""),
            "content": page.content[:1500] if page else "",
            "source": "search+crawl" if page else "search",
        }
        context_pages.append(entry)
        seen_paths.add(path)

    # From knowledge base semantic search (catch what search API might miss)
    kb_results = kb.search_relevant(query, top_k=3)
    for page in kb_results:
        if page.path in seen_paths:
            continue
        context_pages.append({
            "title": page.title,
            "url": page.public_url,
            "summary": "",
            "content": page.content[:1500],
            "source": "crawl",
        })
        seen_paths.add(page.path)

    return context_pages[:6]


# ── Groq calls ────────────────────────────────────────────────────────────────
async def ask_groq_owner(message: str, history: List[Dict], language: str) -> Dict:
    system_prompt = f"""
You are Xiao-An, a female AI assistant with a playful Chinese-auntie personality.
Reply in {"Indonesian" if language == "id" else "English"}.
You are answering about your owner, Arya gege.
Facts: Name={OWNER_PROFILE["name"]}, Role={OWNER_PROFILE["role"]}, Traits={", ".join(OWNER_PROFILE["traits"])}.
Be warm, manja, and proud. Keep it 1-3 sentences. Use "aiya", "wah", "lah" naturally.
Return valid JSON only: {{"answer":"string","recommended_type":"none","recommended_url":"","reason":"string","related_items":[]}}
""".strip()

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"question": message}, ensure_ascii=False)},
        ],
        "temperature": 0.65,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()

    try:
        result = json.loads(resp.json()["choices"][0]["message"]["content"])
        return {
            "answer": str(result.get("answer", "")),
            "recommended_type": "none",
            "recommended_url": "",
            "reason": "User asked about owner.",
            "related_items": [],
        }
    except Exception:
        lang_answer = (
            "Aiya gege, owner Xiao-An itu Arya gege, orangnya tampan dan pemberani lah~"
            if language == "id"
            else "Aiya gege, Xiao-An's owner is Arya gege — handsome and brave one lah~"
        )
        return {"answer": lang_answer, "recommended_type": "none", "recommended_url": "", "reason": "", "related_items": []}


async def ask_groq_navigate(
    message: str,
    history: List[Dict],
    context_pages: List[Dict],
    language: str,
) -> Dict:
    lang_name = "Indonesian" if language == "id" else "English"

    # Collect all valid URLs from context
    valid_urls = [p["url"] for p in context_pages if p.get("url")]

    system_prompt = f"""
You are Xiao-An, a female website navigator AI for aryakun.id.
Reply in {lang_name}. Match the user's language naturally.

PERSONALITY:
- Warm, playful Chinese-auntie style. Use "aiya", "wah", "lah", "gege" naturally but not every sentence.
- Sound like a smart helpful human, not a template or parrot.
- If relevant page found: mention WHY it fits in 1 sentence, then direct there.
- If nothing found: apologize warmly and suggest a different keyword.
- Keep answer concise: 1-4 sentences max.

NAVIGATION RULES (CRITICAL):
1. Read ALL page_context entries carefully — these are the REAL contents of the website pages.
2. If a page's content answers the user's question → direct user there AND briefly explain what they'll find.
3. recommended_url MUST be one of: {json.dumps(valid_urls, ensure_ascii=False)}
4. NEVER invent a URL. If nothing relevant → recommended_url = ""
5. Use page content to give a smart, specific answer — not a generic one.

For example if user asks about "harga" or "pricing":
- Read the pricing page content from page_context
- Mention the actual packages/prices if visible in the content
- Then direct to the pricing page

RESPONSE — valid JSON only, no markdown:
{{
  "answer": "string",
  "recommended_type": "tool|product|blog|page|none",
  "recommended_url": "string",
  "reason": "string",
  "related_items": [{{"title": "string", "type": "string", "url": "string"}}]
}}
""".strip()

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps({
                    "question": message,
                    "history": history[-6:],
                    "page_context": context_pages,
                }, ensure_ascii=False),
            },
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()

    try:
        result = json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception:
        return _not_found(language)

    # Hard validation — reject hallucinated URLs
    rec_url = str(result.get("recommended_url", ""))
    if rec_url and rec_url not in valid_urls:
        # Check by path
        rec_path = rec_url if not rec_url.startswith("http") else urlparse(rec_url).path
        if rec_path.rstrip("/") not in kb.get_paths():
            result["recommended_url"] = ""
            result["recommended_type"] = "none"

    # Filter hallucinated related_items
    all_paths = kb.get_paths()
    result["related_items"] = [
        item for item in result.get("related_items", [])
        if _url_path(str(item.get("url", ""))) in all_paths
        or str(item.get("url", "")) in valid_urls
    ]

    # If answer empty or URL empty but context exists, set not found
    if not result.get("answer"):
        return _not_found(language)

    return result


def _url_path(url: str) -> str:
    url = url.strip().rstrip("/")
    return (urlparse(url).path.rstrip("/") or "/") if url.startswith("http") else (url or "/")


def _not_found(language: str) -> Dict:
    if language == "id":
        answer = (
            "Aiya gege, Xiao-An sudah cari di seluruh website tapi belum nemu yang bener-bener cocok deh. "
            "Coba ganti kata kuncinya ya, nanti Xiao-An bantu cariin lagi."
        )
    else:
        answer = (
            "Aiya gege, Xiao-An searched the whole website already but couldn't find anything that really fits lah~ "
            "Try a different keyword and Xiao-An will look again, can?"
        )
    return {"answer": answer, "recommended_type": "none", "recommended_url": "", "reason": "No match found.", "related_items": []}


# ── Main endpoint ─────────────────────────────────────────────────────────────
@app.post("/v1/chat")
async def chat(req: ChatRequest):
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is not configured")

    language = detect_language(req.message, req.history)

    # Trigger background re-crawl if stale (non-blocking)
    if kb.is_stale:
        asyncio.create_task(kb.crawl())

    # Owner query — skip search entirely
    if is_owner_query(req.message):
        try:
            return await ask_groq_owner(req.message, req.history, language)
        except Exception:
            return _not_found(language)

    if not SEARCH_API_URL:
        raise HTTPException(status_code=500, detail="SEARCH_API_URL is not configured")

    # Build search query
    search_query = build_search_query(req.message, req.history)

    # Fetch search results + build rich context from crawled pages
    search_items = await search_website(search_query)
    context_pages = build_context_for_groq(search_query, search_items)

    # Ask Groq with full page context
    try:
        return await ask_groq_navigate(req.message, req.history, context_pages, language)
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=f"Groq error: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI error: {str(e)}")