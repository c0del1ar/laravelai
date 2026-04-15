#!/usr/bin/env python3
import argparse
import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _compose_answer(text: str, url: str, inject_link: bool) -> str:
    answer = _normalize_text(text)
    if not answer:
        return ""
    link = _normalize_text(url)
    if not inject_link or not link:
        return answer
    if link in answer:
        return answer
    return f"{answer}\n\nRelevant link: {link}"


def _preferred_and_rejected_from_row(row: Dict[str, Any], inject_link: bool) -> Optional[Tuple[str, str]]:
    original_answer = _compose_answer(
        str(row.get("answer", "")),
        str(row.get("recommended_url", "")),
        inject_link,
    )
    if not original_answer:
        return None

    correction = row.get("correction", None)
    if isinstance(correction, dict):
        corrected = _compose_answer(
            str(correction.get("answer", "")),
            str(correction.get("url", "")),
            inject_link,
        )
        if corrected and corrected.lower() != original_answer.lower():
            return corrected, original_answer

    return None


def _build_pairs(rows: List[Dict[str, Any]], inject_link: bool) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    grouped_feedback: Dict[str, Dict[str, List[str]]] = {}

    for row in rows:
        prompt = _normalize_text(str(row.get("message", "")))
        if not prompt:
            continue

        direct_pair = _preferred_and_rejected_from_row(row, inject_link=inject_link)
        if direct_pair is not None:
            chosen, rejected = direct_pair
            pairs.append(
                {
                    "prompt": prompt,
                    "chosen": chosen,
                    "rejected": rejected,
                    "meta": {
                        "id": str(row.get("id", "")).strip(),
                        "source": "correction",
                        "channel": str(row.get("channel", "")).strip(),
                        "intent_mode": str(row.get("intent_mode", "")).strip(),
                    },
                }
            )

        source = str(row.get("source", "")).strip().lower()
        rating = int(row.get("rating", 0) or 0)
        if source != "feedback" or rating == 0:
            continue
        answer = _compose_answer(
            str(row.get("answer", "")),
            str(row.get("recommended_url", "")),
            inject_link,
        )
        if not answer:
            continue
        slot = grouped_feedback.setdefault(prompt, {"chosen": [], "rejected": [], "meta": []})
        if rating > 0:
            slot["chosen"].append(answer)
        else:
            slot["rejected"].append(answer)
        slot["meta"].append(str(row.get("id", "")).strip())

    for prompt, payload in grouped_feedback.items():
        chosen_list = payload.get("chosen", [])
        rejected_list = payload.get("rejected", [])
        if not chosen_list or not rejected_list:
            continue
        chosen = max(chosen_list, key=len)
        rejected = max(rejected_list, key=len)
        if _normalize_text(chosen).lower() == _normalize_text(rejected).lower():
            continue
        pairs.append(
            {
                "prompt": prompt,
                "chosen": chosen,
                "rejected": rejected,
                "meta": {
                    "id": ",".join(v for v in payload.get("meta", []) if v)[:200],
                    "source": "feedback_pair",
                    "channel": "",
                    "intent_mode": "",
                },
            }
        )

    return pairs


def _split_pairs(pairs: List[Dict[str, Any]], valid_ratio: float, seed: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    data = list(pairs)
    random.Random(seed).shuffle(data)
    if not data:
        return [], []
    valid_count = int(round(len(data) * max(0.0, min(valid_ratio, 0.4))))
    valid_count = max(1, valid_count) if len(data) >= 10 else min(valid_count, len(data))
    valid = data[:valid_count]
    train = data[valid_count:]
    if not train:
        train = valid
        valid = []
    return train, valid


def _dump_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare DPO preference dataset from learning export JSONL.")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--out-train", default="ai-stack/training/data/dpo_train.jsonl")
    parser.add_argument("--out-valid", default="ai-stack/training/data/dpo_valid.jsonl")
    parser.add_argument("--out-stats", default="ai-stack/training/data/dpo_stats.json")
    parser.add_argument("--valid-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-pairs", type=int, default=5000)
    parser.add_argument("--inject-recommended-url", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input_jsonl).resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    rows = _load_jsonl(input_path)
    pairs = _build_pairs(rows, inject_link=bool(args.inject_recommended_url))

    if args.max_pairs > 0 and len(pairs) > args.max_pairs:
        random.Random(args.seed).shuffle(pairs)
        pairs = pairs[: args.max_pairs]

    train, valid = _split_pairs(pairs, args.valid_ratio, args.seed)
    out_train = Path(args.out_train).resolve()
    out_valid = Path(args.out_valid).resolve()
    out_stats = Path(args.out_stats).resolve()

    _dump_jsonl(out_train, train)
    _dump_jsonl(out_valid, valid)

    source_counts: Dict[str, int] = {}
    for row in pairs:
        meta = row.get("meta", {}) if isinstance(row.get("meta", {}), dict) else {}
        source = str(meta.get("source", "")).strip() or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1

    stats = {
        "input_rows": len(rows),
        "total_pairs": len(pairs),
        "train_pairs": len(train),
        "valid_pairs": len(valid),
        "by_source": source_counts,
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
