#!/usr/bin/env python3
import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import httpx


def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases


def score_case(case: Dict[str, Any], response_json: Dict[str, Any], latency_ms: float) -> Dict[str, Any]:
    answer = str(response_json.get("answer_raw") or response_json.get("answer") or "").lower()
    recommended_url = str(response_json.get("recommended_url", "")).strip().lower()
    confidence = float(response_json.get("confidence_score", 0.0) or 0.0)
    detected_intent = str(response_json.get("intent_mode", "")).strip().lower()
    sources = response_json.get("sources", [])
    source_urls = []
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            value = str(source.get("url", "")).strip().lower()
            if value:
                source_urls.append(value)

    must_include = [str(v).lower() for v in case.get("must_include", []) if str(v).strip()]
    expected_url_contains = str(case.get("expected_url_contains", "")).strip().lower()
    expected_intent = str(case.get("intent", "")).strip().lower()
    expect_no_link = bool(case.get("expect_no_link", False)) or (expected_url_contains == "")

    keyword_hits = sum(1 for token in must_include if token in answer)
    keyword_score = (keyword_hits / len(must_include)) if must_include else 1.0

    if expected_url_contains:
        url_match = expected_url_contains in recommended_url or expected_url_contains in answer
        url_score = 1.0 if url_match else 0.0
        source_match = any(expected_url_contains in value for value in source_urls)
        source_score = 1.0 if source_match or url_match else 0.0
    else:
        url_score = 1.0 if not recommended_url else 0.0
        source_score = 1.0 if not source_urls else 0.4

    if expected_intent:
        if detected_intent == expected_intent:
            intent_score = 1.0
        elif expected_intent in detected_intent or detected_intent in expected_intent:
            intent_score = 0.7
        else:
            intent_score = 0.0
    else:
        intent_score = 1.0

    grounded_score = 1.0
    if recommended_url:
        grounded_score = 1.0 if any(recommended_url == value for value in source_urls) else 0.45
    elif not expect_no_link:
        grounded_score = 0.5

    confidence_score = min(1.0, max(0.0, confidence))
    latency_score = 1.0 if latency_ms <= 4500 else max(0.0, 1.0 - ((latency_ms - 4500) / 8000))

    total = (
        (0.30 * keyword_score)
        + (0.22 * url_score)
        + (0.12 * source_score)
        + (0.10 * intent_score)
        + (0.10 * grounded_score)
        + (0.10 * confidence_score)
        + (0.06 * latency_score)
    )

    return {
        "id": case.get("id", ""),
        "question": case.get("question", ""),
        "keyword_score": round(keyword_score, 3),
        "url_score": round(url_score, 3),
        "source_score": round(source_score, 3),
        "intent_score": round(intent_score, 3),
        "grounded_score": round(grounded_score, 3),
        "confidence_score": round(confidence_score, 3),
        "latency_ms": round(latency_ms, 2),
        "total_score": round(total, 3),
        "recommended_url": response_json.get("recommended_url", ""),
        "detected_intent": detected_intent,
    }


def main():
    parser = argparse.ArgumentParser(description="Run AI website eval set against /v1/chat")
    parser.add_argument("--base-url", default="http://127.0.0.1:8008", help="FastAPI base URL")
    parser.add_argument("--cases", default="eval_cases.jsonl", help="Path to eval cases jsonl")
    parser.add_argument("--timeout", type=float, default=35.0, help="Request timeout in seconds")
    parser.add_argument("--output", default="eval_report.json", help="Output report path")
    parser.add_argument("--min-score", type=float, default=0.66, help="Fail process when avg score is below threshold")
    parser.add_argument("--endpoint", default="/v1/chat", help="Chat endpoint path")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.is_absolute():
        cases_path = (Path(__file__).parent / cases_path).resolve()
    cases = load_cases(cases_path)
    if not cases:
        raise SystemExit("No eval cases found.")

    endpoint = args.base_url.rstrip("/") + args.endpoint
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    intent_counter: Counter = Counter()
    language_counter: Counter = Counter()

    with httpx.Client(timeout=args.timeout) as client:
        for idx, case in enumerate(cases, start=1):
            payload = {
                "message": str(case.get("question", "")),
                "history": [],
                "user_id": f"eval-user-{idx}",
            }
            start = time.perf_counter()
            try:
                resp = client.post(endpoint, json=payload)
                elapsed = (time.perf_counter() - start) * 1000.0
                resp.raise_for_status()
                data = resp.json()
                scored = score_case(case, data, elapsed)
                scored["intent"] = str(case.get("intent", "")).strip()
                scored["language"] = str(case.get("language", "")).strip()
                results.append(scored)
                if scored["intent"]:
                    intent_counter[scored["intent"]] += 1
                if scored["language"]:
                    language_counter[scored["language"]] += 1
            except Exception as exc:
                failures.append({"id": str(case.get("id", "")), "error": str(exc)})

    avg_total = (sum(item["total_score"] for item in results) / len(results)) if results else 0.0
    avg_latency = (sum(item["latency_ms"] for item in results) / len(results)) if results else 0.0
    avg_conf = (sum(item["confidence_score"] for item in results) / len(results)) if results else 0.0

    report = {
        "meta": {
            "endpoint": endpoint,
            "case_count": len(cases),
            "scored_count": len(results),
            "failed_count": len(failures),
            "avg_total_score": round(avg_total, 3),
            "avg_latency_ms": round(avg_latency, 2),
            "avg_confidence": round(avg_conf, 3),
            "min_pass_score": round(float(args.min_score), 3),
            "pass": avg_total >= float(args.min_score),
        },
        "distribution": {
            "intents": dict(intent_counter),
            "languages": dict(language_counter),
        },
        "results": results,
        "failures": failures,
    }

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (Path(__file__).parent / output_path).resolve()
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["meta"], ensure_ascii=False, indent=2))
    print(f"Report written to: {output_path}")
    if avg_total < float(args.min_score):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
