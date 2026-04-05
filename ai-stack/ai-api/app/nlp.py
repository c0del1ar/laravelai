import re
from typing import Any, Dict, List, Optional, Set

from .html_utils import tokenize_for_search


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
QUERY_STOPWORDS = {
    "yang", "dan", "atau", "untuk", "dari", "dengan", "ke", "di", "itu", "ini", "apa", "siapa",
    "saya", "aku", "kamu", "anda", "kami", "kita", "lah", "dong", "please", "tolong", "bantu",
    "what", "who", "how", "why", "where", "when", "is", "are", "the", "this", "that", "and",
    "or", "to", "for", "of", "in", "on", "a", "an", "can", "could", "would", "should",
    "about", "tell", "me", "you", "your", "my",
}


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

TUTORIAL_MARKERS = [
    "how to use", "cara pakai", "cara menggunakan", "gimana pakai", "tutorial", "langkah",
    "step by step", "how do i use", "how can i use", "penggunaan", "cara kerja tool",
]


def build_search_query(message: str, history: List[Dict[str, Any]]) -> str:
    base_query = extract_core_query(message)
    normalized_message = normalize_text(message)
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


def build_search_queries(message: str, history: List[Dict[str, Any]]) -> List[str]:
    base_query = build_search_query(message, history)
    short_query = extract_core_query(message)
    full_query = normalize_text(message)

    queries: List[str] = []
    seen: Set[str] = set()
    for q in [base_query, short_query, full_query]:
        normalized = normalize_text(q)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        queries.append(normalized)

    fallback = normalize_text(message) or message.strip()
    return queries or [fallback]


def is_tutorial_intent(message: str) -> bool:
    text = normalize_text(message)
    if any(marker in text for marker in TUTORIAL_MARKERS):
        return True
    return ("how" in text and "use" in text) or ("cara" in text and ("pakai" in text or "gunakan" in text))


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
IDENTITY_MARKERS = [
    "siapa kamu", "kamu siapa", "who are you", "what are you",
    "perkenalkan diri", "introduce yourself", "what is your name", "namamu siapa",
    "are you ai", "apakah kamu ai", "xiao an", "xiao-an",
]


def is_owner_query(message: str) -> bool:
    q = normalize_text(message)
    return any(m in q for m in OWNER_MARKERS)


def is_identity_query(message: str) -> bool:
    q = normalize_text(message)
    return any(m in q for m in IDENTITY_MARKERS)


def identity_response(language: str) -> Dict[str, Any]:
    if language == "id":
        answer = (
            "Aiya gege, Xiao-An ini asisten AI milik AryaKun lah. "
            "Xiao-An bantu jawab pertanyaan client tentang layanan, fitur, pricing, dan kebutuhan kamu dengan gaya santai."
        )
    else:
        answer = (
            "Aiya gege, Xiao-An is AryaKun's AI assistant lah. "
            "I help clients with questions about services, features, pricing, and the right next step."
        )

    return {
        "answer": answer,
        "recommended_type": "none",
        "recommended_url": "",
        "reason": "Identity query.",
        "related_items": [],
    }


def query_terms(message: str) -> List[str]:
    tokens = tokenize_for_search(message)
    terms: List[str] = []
    for token in tokens:
        if len(token) <= 2:
            continue
        if token in QUERY_STOPWORDS:
            continue
        terms.append(token)
    return terms
