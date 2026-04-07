import os


def _as_bool(value: str, default: bool = False) -> bool:
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


SEARCH_API_URL = os.getenv("SEARCH_API_URL", "")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
INTERNAL_INDEX_KEY = os.getenv("INTERNAL_INDEX_KEY", SEARCH_API_KEY)
APP_LOG_LEVEL = os.getenv("APP_LOG_LEVEL", "INFO").strip().upper()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_FALLBACK_MODELS = [
    v.strip()
    for v in os.getenv(
        "GROQ_FALLBACK_MODELS",
        "llama-3.1-8b-instant,llama-3.1-70b-versatile,meta-llama/llama-4-scout-17b-16e-instruct",
    ).split(",")
    if v.strip()
]
GROQ_RETRY_MAX_ATTEMPTS = int(os.getenv("GROQ_RETRY_MAX_ATTEMPTS", "3"))
GROQ_RETRY_BASE_DELAY_MS = int(os.getenv("GROQ_RETRY_BASE_DELAY_MS", "350"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local-hash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "256"))
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "/tmp/ai_fastapi_vector_store.db")
SEMANTIC_TOP_K = int(os.getenv("SEMANTIC_TOP_K", "10"))
SEMANTIC_MIN_SCORE = float(os.getenv("SEMANTIC_MIN_SCORE", "0.2"))

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
RAG_RERANK_CANDIDATES = int(os.getenv("RAG_RERANK_CANDIDATES", "24"))
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
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.42"))

AB_EXPERIMENT_ENABLED = _as_bool(os.getenv("AB_EXPERIMENT_ENABLED", "false"))
AB_VARIANTS = [
    v.strip()
    for v in os.getenv("AB_VARIANTS", "control,concise,advisor").split(",")
    if v.strip()
]
AB_MODEL_CONTROL = os.getenv("AB_MODEL_CONTROL", GROQ_MODEL)
AB_MODEL_CONCISE = os.getenv("AB_MODEL_CONCISE", GROQ_MODEL)
AB_MODEL_ADVISOR = os.getenv("AB_MODEL_ADVISOR", GROQ_MODEL)

OPENCLAW_WEBHOOK_KEY = os.getenv("OPENCLAW_WEBHOOK_KEY", "")
OPENCLAW_COMPAT_API_KEY = os.getenv("OPENCLAW_COMPAT_API_KEY", "")
OPENCLAW_COMPAT_MODEL_ID = os.getenv("OPENCLAW_COMPAT_MODEL_ID", "xiao-an")
OPENCLAW_PREFIX_GATE_ENABLED = _as_bool(os.getenv("OPENCLAW_PREFIX_GATE_ENABLED", "false"))
OPENCLAW_REQUIRED_PREFIX = os.getenv("OPENCLAW_REQUIRED_PREFIX", "/ia")
OPENCLAW_PREFIX_GATE_HARD_IGNORE = _as_bool(os.getenv("OPENCLAW_PREFIX_GATE_HARD_IGNORE", "true"))
OPENCLAW_PREFIX_REMINDER_COOLDOWN_SECONDS = int(os.getenv("OPENCLAW_PREFIX_REMINDER_COOLDOWN_SECONDS", str(60 * 60 * 7)))
OPENCLAW_PREFIX_REMINDER_TEXT = os.getenv(
    "OPENCLAW_PREFIX_REMINDER_TEXT",
    "Maaf, Ar gege masih sibuk. Coba kabari lagi nanti atau ngobrol sama aku dulu pakai prefix {prefix} ya.",
)
OPENCLAW_PREFIX_REMINDER_TEXT_EN = os.getenv(
    "OPENCLAW_PREFIX_REMINDER_TEXT_EN",
    "Sorry, Ar gege is still busy right now. Please try again later, or chat with me first using prefix {prefix}.",
)
OPENCLAW_PREFIX_GATE_STORE_PATH = os.getenv("OPENCLAW_PREFIX_GATE_STORE_PATH", "/tmp/ai_fastapi_openclaw_prefix_gate.json")

RESPONSE_CACHE_ENABLED = _as_bool(os.getenv("RESPONSE_CACHE_ENABLED", "true"))
RESPONSE_CACHE_PATH = os.getenv("RESPONSE_CACHE_PATH", "/tmp/ai_fastapi_response_cache.json")
RESPONSE_CACHE_TTL_SECONDS = int(os.getenv("RESPONSE_CACHE_TTL_SECONDS", "900"))
RESPONSE_CACHE_MAX_ITEMS = int(os.getenv("RESPONSE_CACHE_MAX_ITEMS", "1500"))

STRICT_GROUNDING_ENABLED = _as_bool(os.getenv("STRICT_GROUNDING_ENABLED", "true"))
STRICT_GROUNDING_MIN_CONFIDENCE = float(os.getenv("STRICT_GROUNDING_MIN_CONFIDENCE", "0.46"))
STRICT_GROUNDING_REQUIRE_SOURCE = _as_bool(os.getenv("STRICT_GROUNDING_REQUIRE_SOURCE", "true"))

HUMAN_HANDOFF_ENABLED = _as_bool(os.getenv("HUMAN_HANDOFF_ENABLED", "true"))
HUMAN_HANDOFF_LOW_CONF_STREAK = int(os.getenv("HUMAN_HANDOFF_LOW_CONF_STREAK", "2"))
HUMAN_HANDOFF_STATE_PATH = os.getenv("HUMAN_HANDOFF_STATE_PATH", "/tmp/ai_fastapi_handoff_state.json")
HUMAN_HANDOFF_CONTACT_URL = os.getenv("HUMAN_HANDOFF_CONTACT_URL", "/contact")
HUMAN_HANDOFF_KEYWORDS = [
    v.strip().lower()
    for v in os.getenv(
        "HUMAN_HANDOFF_KEYWORDS",
        "admin,operator,cs,customer service,human,real person,staff,agent,orang asli,orang beneran,hubungi tim,telepon,call me",
    ).split(",")
    if v.strip()
]

AUTO_INDEX_ENABLED = _as_bool(os.getenv("AUTO_INDEX_ENABLED", "true"))
AUTO_INDEX_DEBOUNCE_SECONDS = int(os.getenv("AUTO_INDEX_DEBOUNCE_SECONDS", "10"))
AUTO_INDEX_MAX_BATCH = int(os.getenv("AUTO_INDEX_MAX_BATCH", "120"))

GLOSSARY_EXPANSION_ENABLED = _as_bool(os.getenv("GLOSSARY_EXPANSION_ENABLED", "true"))
GLOSSARY_MAX_TERMS = int(os.getenv("GLOSSARY_MAX_TERMS", "12"))

KB_CACHE_PATH = os.getenv("KB_CACHE_PATH", "/tmp/ai_fastapi_kb_cache.json")
MEMORY_STORE_PATH = os.getenv("MEMORY_STORE_PATH", "/tmp/ai_fastapi_memory_store.json")
MEMORY_MAX_TURNS = int(os.getenv("MEMORY_MAX_TURNS", "8"))
MEMORY_TTL_SECONDS = int(os.getenv("MEMORY_TTL_SECONDS", str(60 * 60 * 24 * 7)))
LEARNING_STORE_PATH = os.getenv("LEARNING_STORE_PATH", "/tmp/ai_fastapi_learning_store.json")
LEARNING_MAX_EVENTS = int(os.getenv("LEARNING_MAX_EVENTS", "4000"))

CHANNEL_POLICY_WEB_MAX_SENTENCES = int(os.getenv("CHANNEL_POLICY_WEB_MAX_SENTENCES", "5"))
CHANNEL_POLICY_OPENCLAW_MAX_SENTENCES = int(os.getenv("CHANNEL_POLICY_OPENCLAW_MAX_SENTENCES", "3"))
CHANNEL_POLICY_OPENAI_MAX_SENTENCES = int(os.getenv("CHANNEL_POLICY_OPENAI_MAX_SENTENCES", "4"))

SLO_ALERT_ENABLED = _as_bool(os.getenv("SLO_ALERT_ENABLED", "false"))
SLO_ALERT_WEBHOOK_URL = os.getenv("SLO_ALERT_WEBHOOK_URL", "")
SLO_ALERT_COOLDOWN_SECONDS = int(os.getenv("SLO_ALERT_COOLDOWN_SECONDS", "300"))
SLO_HTTP_5XX_RATE_THRESHOLD = float(os.getenv("SLO_HTTP_5XX_RATE_THRESHOLD", "0.05"))
SLO_CHAT_LATENCY_MS_THRESHOLD = float(os.getenv("SLO_CHAT_LATENCY_MS_THRESHOLD", "5000"))
SLO_CHAT_CONFIDENCE_THRESHOLD = float(os.getenv("SLO_CHAT_CONFIDENCE_THRESHOLD", "0.45"))
SLO_MIN_SAMPLE_SIZE = int(os.getenv("SLO_MIN_SAMPLE_SIZE", "20"))
SITE_NAVIGATION_BRIEF = os.getenv(
    "SITE_NAVIGATION_BRIEF",
    "Fokus website: jelaskan produk/layanan Aryakun secara akurat, utamakan topik pricing, fitur, profile/tentang Aryakun, dan kontak.",
)
