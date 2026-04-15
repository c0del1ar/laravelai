# Fine-Tuning Xiao-An (LoRA)

Folder ini untuk fine-tuning model assistant dari data learning loop yang sudah terkumpul di `ai_fastapi`.

## 1) Install dependency training

```bash
python3 -m venv .venv-train
source .venv-train/bin/activate
pip install -r ai-stack/training/requirements.txt
```

## 2) Export dataset learning dari API

```bash
python3 ai-stack/training/export_learning.py \
  --base-url http://127.0.0.1:8008 \
  --index-key "<INTERNAL_INDEX_KEY>" \
  --limit 5000 \
  --out ai-stack/training/data/learning_export.jsonl
```

## 3) Build dataset SFT

```bash
python3 ai-stack/training/prepare_sft_dataset.py \
  --input-jsonl ai-stack/training/data/learning_export.jsonl \
  --out-train ai-stack/training/data/train.jsonl \
  --out-valid ai-stack/training/data/valid.jsonl \
  --out-stats ai-stack/training/data/stats.json \
  --valid-ratio 0.1 \
  --inject-recommended-url
```

Output format per baris:
- `messages` (ChatML style): system/user/assistant
- `meta`: source, channel, intent, rating, status

## 4) Train LoRA

Contoh (GPU 24GB+, Qwen 7B instruct, 4bit):

```bash
python3 ai-stack/training/train_lora.py \
  --model Qwen/Qwen2.5-7B-Instruct \
  --train-file ai-stack/training/data/train.jsonl \
  --valid-file ai-stack/training/data/valid.jsonl \
  --output-dir ai-stack/training/output/lora-xiaoan-v1 \
  --epochs 2 \
  --lr 2e-4 \
  --batch-size 2 \
  --grad-accum 8 \
  --max-seq-len 2048 \
  --load-in-4bit \
  --bf16 \
  --gradient-checkpointing
```

## 5) Merge adapter (opsional)

```bash
python3 ai-stack/training/merge_lora.py \
  --base-model Qwen/Qwen2.5-7B-Instruct \
  --adapter-path ai-stack/training/output/lora-xiaoan-v1 \
  --output-dir ai-stack/training/output/merged-xiaoan-v1 \
  --bf16
```

## Catatan penting

- Training tidak dijalankan di `ai_fastapi` container produksi; jalankan di worker/GPU terpisah.
- Data source default berasal dari:
  - low-confidence/error logs
  - correction admin
  - feedback `POST /v1/feedback`
- Setelah fine-tune, serve model di endpoint inference terpisah (vLLM/TGI) lalu arahkan AI core ke endpoint itu bila ingin dipakai produksi.
