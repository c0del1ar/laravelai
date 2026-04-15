#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Train DPO adapter from preference pairs.")
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--train-file", required=True)
    parser.add_argument("--valid-file", default="")
    parser.add_argument("--output-dir", default="ai-stack/training/output/dpo-xiaoan")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--lr", type=float, default=5e-6)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--max-prompt-length", type=int, default=1024)
    parser.add_argument("--beta", type=float, default=0.1)
    parser.add_argument("--log-steps", type=int, default=10)
    parser.add_argument("--save-steps", type=int, default=200)
    parser.add_argument("--eval-steps", type=int, default=200)
    parser.add_argument("--lora-r", type=int, default=32)
    parser.add_argument("--lora-alpha", type=int, default=64)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--load-in-4bit", action="store_true")
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--gradient-checkpointing", action="store_true")
    args = parser.parse_args()

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import DPOConfig, DPOTrainer
    except Exception as exc:
        raise SystemExit(
            "Missing training dependencies. Install from ai-stack/training/requirements.txt first.\n"
            f"Original error: {exc}"
        )

    train_path = Path(args.train_file).resolve()
    if not train_path.exists():
        raise SystemExit(f"Train file not found: {train_path}")
    valid_path = Path(args.valid_file).resolve() if args.valid_file else None
    if valid_path and not valid_path.exists():
        raise SystemExit(f"Validation file not found: {valid_path}")

    train_rows = _load_jsonl(train_path)
    valid_rows = _load_jsonl(valid_path) if valid_path and valid_path.exists() else []
    if not train_rows:
        raise SystemExit("DPO train dataset is empty.")

    train_dataset = Dataset.from_list(train_rows)
    eval_dataset = Dataset.from_list(valid_rows) if valid_rows else None

    model_kwargs: Dict[str, Any] = {
        "trust_remote_code": True,
        "device_map": "auto",
    }
    if args.load_in_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if args.bf16 else torch.float16,
        )

    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dpo_args = DPOConfig(
        output_dir=str(output_dir),
        learning_rate=float(args.lr),
        num_train_epochs=float(args.epochs),
        per_device_train_batch_size=int(args.batch_size),
        per_device_eval_batch_size=max(1, int(args.batch_size)),
        gradient_accumulation_steps=int(args.grad_accum),
        max_length=int(args.max_length),
        max_prompt_length=int(args.max_prompt_length),
        beta=float(args.beta),
        eval_strategy="steps" if eval_dataset is not None else "no",
        save_strategy="steps",
        logging_steps=int(args.log_steps),
        save_steps=int(args.save_steps),
        eval_steps=int(args.eval_steps),
        bf16=bool(args.bf16),
        fp16=bool(args.fp16),
        gradient_checkpointing=bool(args.gradient_checkpointing),
        report_to=[],
    )

    trainer = DPOTrainer(
        model=model,
        args=dpo_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        processing_class=tokenizer,
        peft_config=peft_config,
    )

    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    summary = {
        "base_model": args.model,
        "train_pairs": len(train_rows),
        "valid_pairs": len(valid_rows),
        "output_dir": str(output_dir),
    }
    (output_dir / "dpo_training_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
