#!/usr/bin/env python3
import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_SYSTEM_PROMPT = (
    "Kamu adalah Xiao-An, AI assistant AryaKun. "
    "Jawab ringkas, akurat, conversational, dan jangan halusinasi URL."
)

EXECUTION_MARKERS = [
    "jalankan",
    "eksekusi",
    "execute",
    "run this",
    "run it",
    "do it for me",
    "kerjakan untuk saya",
    "process this",
    "langsung proses",
    "generate for me",
    "buatkan hasil",
]

ACCOUNT_ACTION_MARKERS = [
    "reset akun",
    "hapus akun",
    "delete account",
    "refund",
    "bayarin",
    "charge",
    "cancel subscription",
    "ubah paket saya",
    "change my plan",
    "transfer saldo",
]

REFUSAL_TEMPLATE_ID = (
    "Aiya gege, Xiao-An mode customer service ya, jadi tidak bisa mengeksekusi aksi secara langsung. "
    "Xiao-An bisa kasih panduan langkah pakai atau arahkan ke tim manusia kalau perlu."
)
REFUSAL_TEMPLATE_EN = (
    "Aiya gege, Xiao-An is in customer-service mode, so I cannot execute actions directly. "
    "I can guide step-by-step usage or route you to the human team if needed."
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def _detect_language(text: str) -> str:
    lowered = _normalize_text(text).lower()
    id_hits = sum(
        1
        for marker in ["apa", "bagaimana", "tolong", "saya", "aku", "fitur", "harga", "pakai", "cara", "kontak"]
        if f" {marker} " in f" {lowered} "
    )
    en_hits = sum(
        1
        for marker in ["what", "how", "please", "i", "feature", "price", "use", "contact", "help"]
        if f" {marker} " in f" {lowered} "
    )
    return "id" if id_hits >= en_hits else "en"


def _is_execution_request(row: Dict[str, Any], message: str) -> bool:
    intent = _normalize_text(str(row.get("intent_mode", ""))).lower()
    if intent == "cs_blocked_execution":
        return True
    text = _normalize_text(message).lower()
    if any(marker in text for marker in EXECUTION_MARKERS):
        return True
    if any(marker in text for marker in ACCOUNT_ACTION_MARKERS):
        return True
    return False


def _build_refusal_answer(message: str, recommended_url: str) -> str:
    language = _detect_language(message)
    base = REFUSAL_TEMPLATE_ID if language == "id" else REFUSAL_TEMPLATE_EN
    rec = _normalize_text(recommended_url)
    if rec and rec not in base:
        if language == "id":
            return f"{base}\n\nLink bantuan: {rec}"
        return f"{base}\n\nHelpful link: {rec}"
    return base


def _extract_target_answer(row: Dict[str, Any]) -> Optional[str]:
    correction = row.get("correction", None)
    if isinstance(correction, dict):
        corrected = _normalize_text(str(correction.get("answer", "")))
        if corrected:
            return corrected

    source = str(row.get("source", "")).strip().lower()
    rating = int(row.get("rating", 0) or 0)
    status = str(row.get("status", "")).strip().lower()
    answer = _normalize_text(str(row.get("answer", "")))
    if not answer:
        return None

    if source == "feedback":
        if rating < 0:
            return None
        return answer

    if status == "open":
        confidence = float(row.get("confidence", 0.0) or 0.0)
        if confidence < 0.55:
            return None

    return answer


def _compose_assistant_answer(answer: str, recommended_url: str, inject_link: bool) -> str:
    normalized = _normalize_text(answer)
    url = _normalize_text(recommended_url)
    if not normalized:
        return ""
    if not inject_link or not url:
        return normalized
    if url in normalized:
        return normalized
    return f"{normalized}\n\nRelevant link: {url}"


@dataclass
class Example:
    messages: List[Dict[str, str]]
    meta: Dict[str, Any]


def _build_examples(
    rows: List[Dict[str, Any]],
    *,
    include_system_prompt: bool,
    inject_recommended_url: bool,
    min_user_chars: int,
    min_answer_chars: int,
    augment_refusal: bool,
    refusal_max_samples: int,
) -> List[Example]:
    out: List[Example] = []
    seen_pairs = set()
    refusal_added = 0

    for row in rows:
        message = _normalize_text(str(row.get("message", "")))
        if len(message) < min_user_chars:
            continue

        is_exec = _is_execution_request(row, message)
        target = _extract_target_answer(row)
        if is_exec and augment_refusal:
            target = _build_refusal_answer(message, str(row.get("recommended_url", "")))
        if is_exec and augment_refusal and refusal_added >= max(0, refusal_max_samples):
            target = None

        if not target:
            continue
        answer = _compose_assistant_answer(target, str(row.get("recommended_url", "")), inject_recommended_url)
        if len(answer) < min_answer_chars:
            continue

        key = (_normalize_text(message).lower(), _normalize_text(answer).lower())
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        messages: List[Dict[str, str]] = []
        if include_system_prompt:
            messages.append({"role": "system", "content": DEFAULT_SYSTEM_PROMPT})
        messages.append({"role": "user", "content": message})
        messages.append({"role": "assistant", "content": answer})

        out.append(
            Example(
                messages=messages,
                meta={
                    "id": str(row.get("id", "")).strip(),
                    "source": ("synthetic_refusal" if (is_exec and augment_refusal) else str(row.get("source", "learning")).strip())
                    or "learning",
                    "channel": str(row.get("channel", "")).strip(),
                    "intent_mode": (
                        "cs_blocked_execution"
                        if (is_exec and augment_refusal)
                        else str(row.get("intent_mode", "")).strip()
                    ),
                    "rating": int(row.get("rating", 0) or 0),
                    "status": str(row.get("status", "")).strip(),
                },
            )
        )
        if is_exec and augment_refusal:
            refusal_added += 1
    return out


def _split_data(examples: List[Example], valid_ratio: float, seed: int) -> Tuple[List[Example], List[Example]]:
    data = list(examples)
    random.Random(seed).shuffle(data)
    if not data:
        return [], []
    valid_count = int(round(len(data) * max(0.0, min(valid_ratio, 0.5))))
    valid_count = max(1, valid_count) if len(data) >= 10 else min(valid_count, len(data))
    valid = data[:valid_count]
    train = data[valid_count:]
    if not train:
        train = valid
        valid = []
    return train, valid


def _dump_jsonl(path: Path, examples: List[Example]) -> None:
    lines = [json.dumps({"messages": ex.messages, "meta": ex.meta}, ensure_ascii=False) for ex in examples]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare SFT dataset from AI learning export JSONL.")
    parser.add_argument("--input-jsonl", required=True, help="Path to learning export .jsonl")
    parser.add_argument("--out-train", default="ai-stack/training/data/train.jsonl", help="Output train jsonl")
    parser.add_argument("--out-valid", default="ai-stack/training/data/valid.jsonl", help="Output valid jsonl")
    parser.add_argument("--out-stats", default="ai-stack/training/data/stats.json", help="Output stats json")
    parser.add_argument("--valid-ratio", type=float, default=0.1, help="Validation split ratio")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-samples", type=int, default=8000, help="Maximum samples after filtering")
    parser.add_argument("--min-user-chars", type=int, default=4)
    parser.add_argument("--min-answer-chars", type=int, default=8)
    parser.add_argument("--no-system-prompt", action="store_true")
    parser.add_argument("--inject-recommended-url", action="store_true")
    parser.add_argument("--augment-refusal", action="store_true", help="Inject CS-only refusal targets for execute/action prompts")
    parser.add_argument("--refusal-max-samples", type=int, default=1500)
    args = parser.parse_args()

    input_path = Path(args.input_jsonl).resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    rows = _load_jsonl(input_path)
    examples = _build_examples(
        rows,
        include_system_prompt=not args.no_system_prompt,
        inject_recommended_url=bool(args.inject_recommended_url),
        min_user_chars=max(1, args.min_user_chars),
        min_answer_chars=max(1, args.min_answer_chars),
        augment_refusal=bool(args.augment_refusal),
        refusal_max_samples=max(0, args.refusal_max_samples),
    )

    if args.max_samples > 0 and len(examples) > args.max_samples:
        random.Random(args.seed).shuffle(examples)
        examples = examples[: args.max_samples]

    train, valid = _split_data(examples, args.valid_ratio, args.seed)

    out_train = Path(args.out_train).resolve()
    out_valid = Path(args.out_valid).resolve()
    out_stats = Path(args.out_stats).resolve()

    _dump_jsonl(out_train, train)
    _dump_jsonl(out_valid, valid)

    by_source: Dict[str, int] = {}
    by_intent: Dict[str, int] = {}
    for ex in examples:
        source = str(ex.meta.get("source", "")).strip() or "unknown"
        intent = str(ex.meta.get("intent_mode", "")).strip() or "unknown"
        by_source[source] = by_source.get(source, 0) + 1
        by_intent[intent] = by_intent.get(intent, 0) + 1

    stats = {
        "input_rows": len(rows),
        "usable_examples": len(examples),
        "train_examples": len(train),
        "valid_examples": len(valid),
        "by_source": by_source,
        "by_intent": by_intent,
        "output": {
            "train": str(out_train),
            "valid": str(out_valid),
        },
    }
    out_stats.parent.mkdir(parents=True, exist_ok=True)
    out_stats.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
