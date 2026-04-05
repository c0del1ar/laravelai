import os


SEARCH_API_URL = os.getenv("SEARCH_API_URL", "")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

_default_tools_manifest_url = ""
if SEARCH_API_URL and "/internal/ai/search" in SEARCH_API_URL:
    _default_tools_manifest_url = SEARCH_API_URL.replace("/internal/ai/search", "/internal/ai/tools")
TOOL_MANIFEST_API_URL = os.getenv("TOOL_MANIFEST_API_URL", _default_tools_manifest_url)
TOOL_MANIFEST_TTL = int(os.getenv("TOOL_MANIFEST_TTL", "300"))
TOOL_MANIFEST_MAX_ITEMS = int(os.getenv("TOOL_MANIFEST_MAX_ITEMS", "200"))

SITE_BASE_URL = os.getenv("SITE_BASE_URL", "")
SITE_PUBLIC_URL = os.getenv("SITE_PUBLIC_URL", "")

CRAWL_TTL = int(os.getenv("CRAWL_TTL", str(60 * 60 * 6)))
CRAWL_MAX_PAGES = int(os.getenv("CRAWL_MAX_PAGES", "60"))
CRAWL_TIMEOUT = int(os.getenv("CRAWL_TIMEOUT", "8"))
CRAWL_DISCOVERY_MAX_PAGES = int(os.getenv("CRAWL_DISCOVERY_MAX_PAGES", "120"))
CRAWL_PAGE_TEXT_MAX_CHARS = int(os.getenv("CRAWL_PAGE_TEXT_MAX_CHARS", "12000"))

CONTEXT_PAGE_CONTENT_CHARS = int(os.getenv("CONTEXT_PAGE_CONTENT_CHARS", "2200"))
CONTEXT_MAX_PAGES = int(os.getenv("CONTEXT_MAX_PAGES", "8"))

RAG_CHUNK_SIZE_CHARS = int(os.getenv("RAG_CHUNK_SIZE_CHARS", "900"))
RAG_CHUNK_OVERLAP_CHARS = int(os.getenv("RAG_CHUNK_OVERLAP_CHARS", "140"))
RAG_CHUNK_TOP_K = int(os.getenv("RAG_CHUNK_TOP_K", "14"))
RAG_CONTEXT_CHUNKS = int(os.getenv("RAG_CONTEXT_CHUNKS", "6"))
RAG_MAX_CHUNKS_PER_PAGE = int(os.getenv("RAG_MAX_CHUNKS_PER_PAGE", "2"))
SITE_CATALOG_MAX_ITEMS = int(os.getenv("SITE_CATALOG_MAX_ITEMS", "80"))

OPENAI_HISTORY_LIMIT = int(os.getenv("OPENAI_HISTORY_LIMIT", "4"))
OPENAI_MESSAGE_MAX_CHARS = int(os.getenv("OPENAI_MESSAGE_MAX_CHARS", "1800"))

LLM_MAX_INPUT_TOKENS = int(os.getenv("LLM_MAX_INPUT_TOKENS", "2600"))
LLM_MAX_HISTORY_MESSAGES = int(os.getenv("LLM_MAX_HISTORY_MESSAGES", "4"))
LLM_MAX_HISTORY_CHARS = int(os.getenv("LLM_MAX_HISTORY_CHARS", "600"))
LLM_MAX_CONTEXT_PAGES = int(os.getenv("LLM_MAX_CONTEXT_PAGES", "6"))
LLM_MAX_CONTEXT_CONTENT_CHARS = int(os.getenv("LLM_MAX_CONTEXT_CONTENT_CHARS", "900"))
LLM_MAX_CONTEXT_SUMMARY_CHARS = int(os.getenv("LLM_MAX_CONTEXT_SUMMARY_CHARS", "260"))
LLM_MAX_SITE_CATALOG = int(os.getenv("LLM_MAX_SITE_CATALOG", "30"))
LLM_MAX_TOOL_MANIFESTS = int(os.getenv("LLM_MAX_TOOL_MANIFESTS", "2"))
LLM_MAX_TOOL_FIELDS = int(os.getenv("LLM_MAX_TOOL_FIELDS", "8"))
LLM_MAX_TOOL_STEPS = int(os.getenv("LLM_MAX_TOOL_STEPS", "6"))

OPENCLAW_WEBHOOK_KEY = os.getenv("OPENCLAW_WEBHOOK_KEY", "")
OPENCLAW_COMPAT_API_KEY = os.getenv("OPENCLAW_COMPAT_API_KEY", "")
OPENCLAW_COMPAT_MODEL_ID = os.getenv("OPENCLAW_COMPAT_MODEL_ID", "xiao-an")

KB_CACHE_PATH = os.getenv("KB_CACHE_PATH", "/tmp/ai_fastapi_kb_cache.json")
SITE_NAVIGATION_BRIEF = os.getenv(
    "SITE_NAVIGATION_BRIEF",
    "Fokus website: jelaskan produk/layanan Aryakun secara akurat, utamakan topik pricing, fitur, profile/tentang Aryakun, dan kontak.",
)
