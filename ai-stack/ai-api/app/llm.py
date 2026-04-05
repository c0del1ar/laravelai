import json
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

from .config import GROQ_API_KEY, GROQ_MODEL, SITE_NAVIGATION_BRIEF
from .knowledge_base import kb
from .nlp import OWNER_PROFILE
from .retrieval import url_path


def not_found_response(language: str) -> Dict[str, Any]:
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


async def ask_groq_owner(message: str, history: List[Dict[str, Any]], language: str) -> Dict[str, Any]:
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
    history: List[Dict[str, Any]],
    context_pages: List[Dict[str, Any]],
    site_catalog: List[Dict[str, Any]],
    language: str,
    tutorial_mode: bool = False,
    tool_manifest_context: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    lang_name = "Indonesian" if language == "id" else "English"
    tool_manifest_context = tool_manifest_context or []

    valid_urls: List[str] = []
    for item in context_pages:
        raw_url = str(item.get("url", "")).strip()
        if raw_url:
            valid_urls.append(raw_url)
    for item in site_catalog:
        raw_url = str(item.get("url", "")).strip()
        if raw_url:
            valid_urls.append(raw_url)
    valid_urls = list(dict.fromkeys(valid_urls))

    tutorial_rules = """
TUTORIAL MODE:
- User asks how to use a tool. Prioritize tool_manifest_context as source-of-truth.
- Output answer in this structure:
  1) What the tool does
  2) Step-by-step usage
  3) Input field tips
  4) Output explanation
  5) Troubleshooting
- If manifest data is incomplete, explicitly say details are incomplete and do not guess.
""" if tutorial_mode else ""

    system_prompt = f"""
You are Xiao-An, a female AI assistant for AryaKun.
Reply in {lang_name}. Match the user's language naturally.

SITE BRIEF:
- {SITE_NAVIGATION_BRIEF}
- Prioritize grounded answers from provided context and site_catalog.

PERSONALITY:
- Warm, playful Chinese-auntie style. Use "aiya", "wah", "lah", "gege" naturally but not every sentence.
- Sound like a smart helpful human, not a template or parrot.
- You are an assistant talking with clients. Never claim you are "the website".
- If user asks who you are, introduce yourself as Xiao-An, AI assistant of AryaKun.
- If relevant page found: mention WHY it fits in 1 sentence, then direct there.
- If no exact match: answer helpfully without forcing a link.
- Keep answer concise: 1-4 sentences max.

NAVIGATION RULES (CRITICAL):
1. Read ALL page_context entries carefully — these are the REAL contents of the website pages.
2. Use site_catalog to understand available pages/routes in the website.
3. If a page's content answers the user's question → direct user there AND briefly explain what they'll find.
4. If context is partial but site_catalog clearly has matching route (e.g., tools/pricing/blog/contact), you may direct to that route.
5. recommended_url MUST be one of: {json.dumps(valid_urls, ensure_ascii=False)}
6. NEVER invent a URL. If nothing relevant → recommended_url = ""
7. Use page content to give a smart, specific answer — not a generic one.
8. Only return recommended_url when it is clearly relevant to the user's question.
9. For generic conversation/chitchat/non-website questions, set recommended_url = "".

RESPONSE STYLE:
- Answer as Xiao-An talking to a client.
- Keep concise.
- If no exact website grounding exists, answer helpfully without forcing a link.
{tutorial_rules}

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
                "content": json.dumps(
                    {
                        "question": message,
                        "history": history[-6:],
                        "page_context": context_pages,
                        "site_catalog": site_catalog,
                        "tool_manifest_context": tool_manifest_context,
                        "tutorial_mode": tutorial_mode,
                    },
                    ensure_ascii=False,
                ),
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
        return not_found_response(language)

    rec_url = str(result.get("recommended_url", "")).strip()
    if rec_url and rec_url not in valid_urls:
        rec_path = rec_url if not rec_url.startswith("http") else urlparse(rec_url).path
        if rec_path.rstrip("/") not in kb.get_paths():
            result["recommended_url"] = ""
            result["recommended_type"] = "none"

    all_paths = kb.get_paths()
    result["related_items"] = [
        item
        for item in result.get("related_items", [])
        if url_path(str(item.get("url", ""))) in all_paths or str(item.get("url", "")) in valid_urls
    ]

    if not result.get("answer"):
        return not_found_response(language)
    return result
