import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from typing import List, Set

from .config import CRAWL_PAGE_TEXT_MAX_CHARS, RAG_CHUNK_OVERLAP_CHARS, RAG_CHUNK_SIZE_CHARS


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


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = ""
        for key, value in attrs:
            if key == "href":
                href = (value or "").strip()
                break
        if href:
            self.links.append(href)


class FormExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms: List[dict] = []
        self._active_form: dict | None = None
        self._active_field: dict | None = None
        self._active_select: dict | None = None
        self._active_button_text: List[str] = []

    @staticmethod
    def _attrs_to_dict(attrs) -> dict:
        data: dict = {}
        for k, v in attrs:
            data[str(k)] = "" if v is None else str(v)
        return data

    def _push_field(self, field: dict):
        if not self._active_form:
            return
        key = str(field.get("key", "")).strip()
        label = str(field.get("label", "")).strip()
        if not key and not label:
            return
        self._active_form["fields"].append(field)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        data = self._attrs_to_dict(attrs)

        if tag == "form":
            self._active_form = {
                "action": data.get("action", "").strip(),
                "method": data.get("method", "get").strip().lower() or "get",
                "fields": [],
                "buttons": [],
            }
            return

        if not self._active_form:
            return

        if tag == "input":
            field_type = (data.get("type", "text") or "text").strip().lower()
            if field_type in {"submit", "button"}:
                btn_text = data.get("value", "").strip()
                if btn_text:
                    self._active_form["buttons"].append(btn_text)
                return
            field = {
                "key": (data.get("name") or data.get("id") or "").strip(),
                "label": (
                    data.get("aria-label")
                    or data.get("title")
                    or data.get("placeholder")
                    or data.get("name")
                    or data.get("id")
                    or ""
                ).strip(),
                "type": field_type,
                "required": "required" in data,
                "placeholder": data.get("placeholder", "").strip(),
                "accept": data.get("accept", "").strip(),
                "options": [],
            }
            self._push_field(field)
            return

        if tag == "textarea":
            field = {
                "key": (data.get("name") or data.get("id") or "").strip(),
                "label": (
                    data.get("aria-label")
                    or data.get("title")
                    or data.get("placeholder")
                    or data.get("name")
                    or data.get("id")
                    or ""
                ).strip(),
                "type": "textarea",
                "required": "required" in data,
                "placeholder": data.get("placeholder", "").strip(),
                "accept": "",
                "options": [],
            }
            self._active_field = field
            return

        if tag == "select":
            field = {
                "key": (data.get("name") or data.get("id") or "").strip(),
                "label": (
                    data.get("aria-label")
                    or data.get("title")
                    or data.get("name")
                    or data.get("id")
                    or ""
                ).strip(),
                "type": "select",
                "required": "required" in data,
                "placeholder": "",
                "accept": "",
                "options": [],
            }
            self._active_select = field
            return

        if tag == "option" and self._active_select is not None:
            option_value = data.get("value", "").strip()
            option_label = option_value
            self._active_select["options"].append({"value": option_value, "label": option_label})
            return

        if tag == "button":
            self._active_button_text = []
            self._active_field = {"_button_capture": True}

    def handle_data(self, data):
        if self._active_select is not None and self._active_select.get("options"):
            opt = self._active_select["options"][-1]
            if not opt.get("label"):
                label = data.strip()
                if label:
                    opt["label"] = label

        if self._active_field and self._active_field.get("_button_capture"):
            text = data.strip()
            if text:
                self._active_button_text.append(text)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "form":
            if self._active_form:
                self.forms.append(self._active_form)
            self._active_form = None
            self._active_field = None
            self._active_select = None
            self._active_button_text = []
            return

        if not self._active_form:
            return

        if tag == "textarea" and self._active_field and not self._active_field.get("_button_capture"):
            self._push_field(self._active_field)
            self._active_field = None
            return

        if tag == "select" and self._active_select is not None:
            self._push_field(self._active_select)
            self._active_select = None
            return

        if tag == "button" and self._active_field and self._active_field.get("_button_capture"):
            text = " ".join(self._active_button_text).strip()
            if text:
                self._active_form["buttons"].append(text)
            self._active_button_text = []
            self._active_field = None


def tokenize_for_search(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1]


def normalize_path(path: str) -> str:
    path = path.strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def is_probably_html_path(path: str) -> bool:
    blocked_ext = (
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
        ".css", ".js", ".mjs", ".map", ".xml", ".json", ".txt",
        ".pdf", ".zip", ".gz", ".rar", ".7z", ".mp4", ".mp3",
    )
    lower = path.lower()
    return not any(lower.endswith(ext) for ext in blocked_ext)


def extract_internal_paths_from_html(html: str, current_url: str, base_url: str) -> Set[str]:
    parser = LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        return set()

    base_netloc = urlparse(base_url).netloc
    found: Set[str] = set()

    for href in parser.links:
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        abs_url = urljoin(current_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc != base_netloc:
            continue

        path = normalize_path(parsed.path or "/")
        if not is_probably_html_path(path):
            continue
        found.add(path)

    return found


def extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return ""


def extract_text_from_html(html: str, max_chars: int = CRAWL_PAGE_TEXT_MAX_CHARS) -> str:
    parser = TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = parser.get_text()
    return text[:max_chars]


def chunk_text(
    text: str,
    size: int = RAG_CHUNK_SIZE_CHARS,
    overlap: int = RAG_CHUNK_OVERLAP_CHARS,
) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: List[str] = []
    step = max(1, size - overlap)
    start = 0
    n = len(text)

    while start < n:
        end = min(n, start + size)
        piece = text[start:end]

        if end < n:
            cut = max(piece.rfind(". "), piece.rfind("! "), piece.rfind("? "), piece.rfind("; "), piece.rfind(", "))
            if cut > size // 3:
                piece = piece[:cut + 1]
                end = start + cut + 1

        piece = piece.strip()
        if piece:
            chunks.append(piece)

        if end >= n:
            break
        start += step

    return chunks


def extract_forms_from_html(html: str) -> List[dict]:
    parser = FormExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []

    cleaned: List[dict] = []
    for form in parser.forms:
        fields = []
        for field in form.get("fields", []):
            key = str(field.get("key", "")).strip()
            label = str(field.get("label", "")).strip()
            if not key and not label:
                continue
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "type": str(field.get("type", "text")).strip() or "text",
                    "required": bool(field.get("required", False)),
                    "placeholder": str(field.get("placeholder", "")).strip(),
                    "accept": str(field.get("accept", "")).strip(),
                    "options": field.get("options", []) if isinstance(field.get("options", []), list) else [],
                }
            )

        if not fields:
            continue

        cleaned.append(
            {
                "action": str(form.get("action", "")).strip(),
                "method": str(form.get("method", "get")).strip().lower() or "get",
                "fields": fields,
                "buttons": [str(v).strip() for v in form.get("buttons", []) if str(v).strip()],
            }
        )

    return cleaned
