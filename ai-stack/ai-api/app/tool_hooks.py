from typing import Any, Dict, List


def _noredirect_hook(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "examples": [
            {"label": "valid_url", "value": "https://example.com"},
            {"label": "invalid_url", "value": "example without protocol"},
        ],
        "tips": [
            "Gunakan URL lengkap dengan http:// atau https://.",
            "Cek output source/raw HTML untuk verifikasi redirect script/meta refresh.",
        ],
    }


def _default_hook(manifest: Dict[str, Any]) -> Dict[str, Any]:
    fields = (((manifest.get("input_schema", {}) or {}).get("fields", [])) or [])
    examples: List[Dict[str, str]] = []
    for field in fields[:4]:
        if not isinstance(field, dict):
            continue
        key = str(field.get("key", "")).strip() or str(field.get("label", "")).strip()
        if not key:
            continue
        ftype = str(field.get("type", "text")).strip()
        value = "contoh input"
        if ftype in {"url", "link"}:
            value = "https://example.com"
        elif ftype in {"email"}:
            value = "name@example.com"
        elif ftype in {"number", "integer"}:
            value = "10"
        examples.append({"label": key, "value": value})
    return {
        "examples": examples,
        "tips": ["Isi field wajib dulu, lalu jalankan tool dan cek output/result section."],
    }


HOOKS = {
    "noredirect": _noredirect_hook,
}


def apply_tool_hook(manifest: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(manifest)
    slug = str(payload.get("slug", "")).strip().lower()
    hook_fn = HOOKS.get(slug, _default_hook)
    hook_payload = hook_fn(payload)
    payload["hook"] = hook_payload
    return payload
