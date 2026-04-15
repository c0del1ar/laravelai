from typing import Any, Dict, List

from .html_utils import tokenize_for_search
from .nlp import build_search_queries, classify_intent_mode, is_tutorial_intent, normalize_text


INTENT_ALIASES: Dict[str, List[str]] = {
    "blog": ["blog", "artikel", "article", "post", "news", "insight"],
    "product": ["product", "produk", "service", "layanan"],
    "tools": ["tools", "tool", "checker", "generator", "utility", "utilities"],
    "feature": ["feature", "fitur", "capability", "kelebihan", "fungsi"],
    "pricing": ["pricing", "harga", "paket", "plan", "biaya", "subscription"],
    "contact": ["contact", "kontak", "support", "cs", "whatsapp", "telegram", "discord", "email"],
    "about": ["about", "tentang", "siapa aryakun", "company", "profil"],
}


def extract_tool_slug_hint(message: str) -> str:
    text = normalize_text(message)
    if "/tools/" in text:
        after = text.split("/tools/", 1)[1]
        slug = after.split()[0].strip().strip("/").strip(".:,;!?")
        if slug:
            return slug

    tokens = tokenize_for_search(text)
    if not tokens:
        return ""

    direct = {"noredirect", "no-redirect", "redirectchecker", "redirect-checker"}
    for token in tokens:
        if token in direct:
            return "noredirect"

    idx = -1
    for i, token in enumerate(tokens):
        if token in {"tool", "tools"} and i + 1 < len(tokens):
            idx = i + 1
            break
    if idx >= 0:
        candidate = tokens[idx].strip("-_ ")
        if candidate:
            return candidate
    return ""


def classify_intent_profile(message: str) -> Dict[str, Any]:
    base_mode = classify_intent_mode(message)
    text = normalize_text(message)
    mode = base_mode
    topic = "general"

    if any(term in text for term in INTENT_ALIASES["blog"]):
        topic = "blog"
        if mode == "navigation":
            mode = "blog"
    elif any(term in text for term in INTENT_ALIASES["product"]):
        topic = "product"
        if mode == "navigation":
            mode = "product"
    elif any(term in text for term in INTENT_ALIASES["tools"]):
        topic = "tools"
        if mode == "navigation":
            mode = "tools"
    elif any(term in text for term in INTENT_ALIASES["feature"]):
        topic = "feature"
        if mode == "navigation":
            mode = "feature"
    elif any(term in text for term in INTENT_ALIASES["about"]):
        topic = "about"
        if mode == "navigation":
            mode = "about"
    elif mode in {"pricing", "contact"}:
        topic = mode

    tutorial_mode = mode == "tutorial" or is_tutorial_intent(message)
    tool_slug_hint = extract_tool_slug_hint(message) if tutorial_mode else ""

    return {
        "intent_mode": mode,
        "topic": topic,
        "tutorial_mode": tutorial_mode,
        "tool_slug_hint": tool_slug_hint,
    }


def expand_queries_for_intent(
    message: str,
    history: List[Dict[str, Any]],
    profile: Dict[str, Any],
) -> List[str]:
    queries = build_search_queries(message, history)
    mode = str(profile.get("intent_mode", "navigation")).strip() or "navigation"
    topic = str(profile.get("topic", "general")).strip()
    tool_slug_hint = str(profile.get("tool_slug_hint", "")).strip()

    extras: List[str] = []
    if mode == "pricing":
        extras.append("pricing harga paket plan biaya subscription")
    elif mode == "contact":
        extras.append("contact kontak support whatsapp email telegram discord")
    elif mode == "tutorial":
        extras.append("cara pakai tutorial step by step input output troubleshooting")
    elif mode == "blog":
        extras.append("blog artikel post tutorial insight")
    elif mode == "product":
        extras.append("product produk layanan use case")
    elif mode == "feature":
        extras.append("fitur feature capability kelebihan fungsi")
    elif mode == "about":
        extras.append("about tentang profil siapa aryakun")
    elif mode == "troubleshoot":
        extras.append("error issue not working troubleshooting panduan")

    if topic and topic not in {"general", mode}:
        extras.append(topic)
    if tool_slug_hint:
        extras.append(tool_slug_hint)

    merged: List[str] = []
    seen = set()
    for item in queries + extras:
        q = normalize_text(item)
        if not q or q in seen:
            continue
        seen.add(q)
        merged.append(q)

    return merged or queries
