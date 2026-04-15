#!/usr/bin/env python3
import argparse
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Export learning events from ai_fastapi /admin/learning/export.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8008")
    parser.add_argument("--index-key", required=True)
    parser.add_argument("--limit", type=int, default=3000)
    parser.add_argument("--out", default="ai-stack/training/data/learning_export.jsonl")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    endpoint = f"{args.base_url.rstrip('/')}/admin/learning/export"
    params = {"limit": max(1, min(args.limit, 10000))}
    headers = {"X-Index-Key": args.index_key}

    with httpx.Client(timeout=args.timeout) as client:
        response = client.get(endpoint, params=params, headers=headers)
        response.raise_for_status()
        payload = response.text

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")
    print(f"Learning export saved to: {out_path}")


if __name__ == "__main__":
    main()
