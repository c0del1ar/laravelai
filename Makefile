SHELL := /bin/sh

EVAL_BASE_URL ?= http://127.0.0.1:8008
EVAL_MIN_SCORE ?= 0.66

.PHONY: eval eval-ci eval-compile

eval:
	./ai-stack/evals/run_regression.sh "$(EVAL_BASE_URL)" "$(EVAL_MIN_SCORE)"

eval-ci: eval

eval-compile:
	python3 -m py_compile ai-stack/ai-api/app/*.py ai-stack/evals/run_eval.py
