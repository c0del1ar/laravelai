SHELL := /bin/sh

EVAL_BASE_URL ?= http://127.0.0.1:8008
EVAL_MIN_SCORE ?= 0.66
FT_BASE_URL ?= http://127.0.0.1:8008
FT_LIMIT ?= 5000
FT_DATA_DIR ?= ai-stack/training/data

.PHONY: eval eval-ci eval-compile ft-export ft-prepare

eval:
	./ai-stack/evals/run_regression.sh "$(EVAL_BASE_URL)" "$(EVAL_MIN_SCORE)"

eval-ci: eval

eval-compile:
	python3 -m py_compile \
		ai-stack/ai-api/app/*.py \
		ai-stack/evals/run_eval.py \
		ai-stack/training/export_learning.py \
		ai-stack/training/prepare_sft_dataset.py \
		ai-stack/training/train_lora.py \
		ai-stack/training/merge_lora.py

ft-export:
	@test -n "$(INDEX_KEY)" || (echo "INDEX_KEY is required. Example: make ft-export INDEX_KEY=xxx"; exit 1)
	python3 ai-stack/training/export_learning.py \
		--base-url "$(FT_BASE_URL)" \
		--index-key "$(INDEX_KEY)" \
		--limit "$(FT_LIMIT)" \
		--out "$(FT_DATA_DIR)/learning_export.jsonl"

ft-prepare:
	python3 ai-stack/training/prepare_sft_dataset.py \
		--input-jsonl "$(FT_DATA_DIR)/learning_export.jsonl" \
		--out-train "$(FT_DATA_DIR)/train.jsonl" \
		--out-valid "$(FT_DATA_DIR)/valid.jsonl" \
		--out-stats "$(FT_DATA_DIR)/stats.json" \
		--valid-ratio 0.1 \
		--inject-recommended-url
