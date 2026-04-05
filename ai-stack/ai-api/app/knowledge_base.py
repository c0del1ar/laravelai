import json
import time
import asyncio
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import urlparse
from typing import Dict, List, Optional, Set

import httpx

from .config import (
    CRAWL_DISCOVERY_MAX_PAGES,
    CRAWL_MAX_PAGES,
    CRAWL_TIMEOUT,
    CRAWL_TTL,
    KB_CACHE_PATH,
    RAG_CHUNK_TOP_K,
    SITE_BASE_URL,
    SITE_CATALOG_MAX_ITEMS,
    SITE_PUBLIC_URL,
)
from .html_utils import (
    chunk_text,
    extract_internal_paths_from_html,
    extract_forms_from_html,
    extract_text_from_html,
    extract_title,
    normalize_path,
    tokenize_for_search,
)


class PageInfo:
    __slots__ = ("path", "public_url", "title", "content", "forms", "crawled_at")

    def __init__(self, path: str, public_url: str, title: str, content: str, forms: Optional[List[Dict]] = None):
        self.path = path
        self.public_url = public_url
        self.title = title
        self.content = content
        self.forms = forms or []
        self.crawled_at = time.time()


class WebsiteKnowledgeBase:
    def __init__(self):
        self._pages: Dict[str, PageInfo] = {}
        self._chunks: List[Dict[str, str]] = []
        self._catalog: List[Dict[str, str]] = []
        self._crawled_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_stale(self) -> bool:
        return (time.time() - self._crawled_at) > CRAWL_TTL

    @property
    def page_count(self) -> int:
        return len(self._pages)

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def catalog_count(self) -> int:
        return len(self._catalog)

    def get_paths(self) -> Set[str]:
        return set(self._pages.keys())

    def get_page(self, path: str) -> Optional[PageInfo]:
        return self._pages.get(path.rstrip("/") or "/")

    def get_catalog(self, max_items: int = SITE_CATALOG_MAX_ITEMS) -> List[Dict[str, str]]:
        return [dict(item) for item in self._catalog[:max_items]]

    def _rebuild_catalog(self):
        catalog: List[Dict[str, str]] = []
        for page in self._pages.values():
            path = normalize_path(page.path)
            slug = path.strip("/")
            section = slug.split("/", 1)[0] if slug else "home"
            catalog.append(
                {
                    "path": path,
                    "url": page.public_url,
                    "title": page.title or path,
                    "section": section or "home",
                }
            )
        catalog.sort(key=lambda item: (item["path"].count("/"), len(item["path"]), item["path"]))
        self._catalog = catalog

    def _rebuild_chunks(self):
        chunks: List[Dict[str, str]] = []
        for page in self._pages.values():
            for idx, piece in enumerate(chunk_text(page.content)):
                chunks.append(
                    {
                        "path": page.path,
                        "url": page.public_url,
                        "title": page.title,
                        "chunk_id": f"{page.path}#{idx}",
                        "content": piece,
                    }
                )
        self._chunks = chunks

    def _save_cache(self):
        try:
            if not self._pages:
                return
            payload = {
                "crawled_at": self._crawled_at,
                "pages": [
                    {
                        "path": page.path,
                        "public_url": page.public_url,
                        "title": page.title,
                        "content": page.content,
                        "forms": page.forms,
                    }
                    for page in self._pages.values()
                ],
            }
            with open(KB_CACHE_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except Exception:
            pass

    def load_cache(self):
        try:
            with open(KB_CACHE_PATH, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            return

        pages = payload.get("pages", [])
        if not isinstance(pages, list):
            return

        loaded: Dict[str, PageInfo] = {}
        for item in pages:
            if not isinstance(item, dict):
                continue
            path = normalize_path(str(item.get("path", "")))
            public_url = str(item.get("public_url", "")).strip()
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            forms = item.get("forms", [])
            forms = forms if isinstance(forms, list) else []
            if not path or not public_url:
                continue
            if not content and not title:
                continue
            loaded[path] = PageInfo(path=path, public_url=public_url, title=title, content=content, forms=forms)

        if not loaded:
            return

        self._pages = loaded
        self._rebuild_chunks()
        self._rebuild_catalog()
        crawled_at = float(payload.get("crawled_at", 0) or 0)
        self._crawled_at = crawled_at if crawled_at > 0 else time.time()

    def search_relevant(self, query: str, top_k: int = 4) -> List[PageInfo]:
        terms = tokenize_for_search(query)
        if not terms:
            return []

        scored: List[tuple] = []
        for page in self._pages.values():
            title_tokens = tokenize_for_search(page.title)
            path_tokens = tokenize_for_search(page.path.replace("/", " "))
            content_tokens = tokenize_for_search(page.content)
            content_tf = Counter(content_tokens)

            score = 0.0
            for term in terms:
                if term in title_tokens:
                    score += 6.0
                if term in path_tokens:
                    score += 5.0
                tf = min(content_tf.get(term, 0), 5)
                if tf > 0:
                    score += 1.5 * tf

            matched_terms = sum(
                1 for term in set(terms) if term in title_tokens or term in path_tokens or term in content_tf
            )
            score += matched_terms * 1.2

            if score > 0:
                scored.append((score, page))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]

    def search_relevant_chunks(self, query: str, top_k: int = RAG_CHUNK_TOP_K) -> List[Dict[str, str]]:
        terms = tokenize_for_search(query)
        if not terms or not self._chunks:
            return []

        scored: List[tuple] = []
        for chunk in self._chunks:
            title_tokens = tokenize_for_search(chunk.get("title", ""))
            path_tokens = tokenize_for_search(chunk.get("path", "").replace("/", " "))
            content_tokens = tokenize_for_search(chunk.get("content", ""))
            content_tf = Counter(content_tokens)

            score = 0.0
            for term in terms:
                if term in title_tokens:
                    score += 4.5
                if term in path_tokens:
                    score += 4.0
                tf = min(content_tf.get(term, 0), 5)
                if tf > 0:
                    score += 1.8 * tf

            matched_terms = sum(
                1 for term in set(terms) if term in title_tokens or term in path_tokens or term in content_tf
            )
            score += matched_terms * 1.4

            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        ranked: List[Dict[str, str]] = []
        for score, item in scored[:top_k]:
            payload = dict(item)
            payload["score"] = f"{score:.4f}"
            ranked.append(payload)
        return ranked

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

        sitemap_paths = await self._fetch_sitemap_paths(base)
        seed_paths = {normalize_path(p) for p in sitemap_paths}
        seed_paths.add("/")

        discovered_paths = await self._discover_paths_from_links(base, seed_paths)
        paths = seed_paths | discovered_paths

        ordered_paths = sorted(paths, key=lambda p: (p.count("/"), len(p), p))
        sem = asyncio.Semaphore(8)
        tasks = [self._crawl_page(base, public_base, path, sem) for path in ordered_paths[:CRAWL_MAX_PAGES]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        new_pages: Dict[str, PageInfo] = {}
        for r in results:
            if isinstance(r, PageInfo):
                new_pages[r.path] = r

        self._pages = new_pages
        self._rebuild_chunks()
        self._rebuild_catalog()
        self._crawled_at = time.time()
        self._save_cache()

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

    async def _discover_paths_from_links(self, base: str, seed_paths: Set[str]) -> Set[str]:
        discovered: Set[str] = set()
        queue: List[str] = [normalize_path(p) for p in sorted(seed_paths)]
        seen: Set[str] = set()

        max_pages = max(CRAWL_MAX_PAGES, CRAWL_DISCOVERY_MAX_PAGES)

        try:
            async with httpx.AsyncClient(timeout=CRAWL_TIMEOUT) as client:
                while queue and len(seen) < max_pages:
                    path = normalize_path(queue.pop(0))
                    if path in seen:
                        continue
                    seen.add(path)

                    try:
                        url = base + path
                        resp = await client.get(url, headers={"Accept": "text/html"}, follow_redirects=True)
                        if resp.status_code != 200:
                            continue
                        content_type = str(resp.headers.get("content-type", "")).lower()
                        if "text/html" not in content_type:
                            continue
                        html = resp.text
                    except Exception:
                        continue

                    discovered.add(path)
                    linked_paths = extract_internal_paths_from_html(html, url, base)
                    for linked_path in linked_paths:
                        norm = normalize_path(linked_path)
                        if norm in seen or norm in queue:
                            continue
                        if len(seen) + len(queue) >= max_pages * 2:
                            break
                        queue.append(norm)
        except Exception:
            return discovered

        return discovered

    async def _crawl_page(
        self, base: str, public_base: str, path: str, sem: asyncio.Semaphore
    ) -> Optional[PageInfo]:
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
                forms = extract_forms_from_html(html)
                if not content and not title:
                    return None

                return PageInfo(path=path, public_url=public_base + path, title=title, content=content, forms=forms)
            except Exception:
                return None


kb = WebsiteKnowledgeBase()
