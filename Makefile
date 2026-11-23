.PHONY: sync test lint typecheck check run-sample eval run-full usage package clean

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

sync:
	uv sync --extra dev

test:
	$(PYTEST) tests/
	$(RUFF) check src/ tests/ evaluation/
	$(MYPY) src/

lint:
	$(RUFF) check src/ tests/ evaluation/

typecheck:
	$(MYPY) src/

check: test

run-sample:
	$(PYTHON) -m deletion_audit.cli run --split sample --output sample_predictions.csv

eval: run-sample
	$(PYTHON) -m deletion_audit.cli eval --predictions sample_predictions.csv --gold dataset/sample_output.csv --report evaluation/evaluation_report.md

run-full:
	$(PYTHON) -m deletion_audit.cli run --split full --output output.csv
	$(PYTHON) -m deletion_audit.cli usage --report evaluation/usage_report.md

usage:
	$(PYTHON) -m deletion_audit.cli usage --report evaluation/usage_report.md

package:
	rm -f code.zip
	zip -r code.zip README.md pyproject.toml uv.lock Makefile Dockerfile .env.example prompts src code evaluation docs tests \
		-x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/.git/*" "*/.DS_Store" "*/.pytest_cache/*" "*/.mypy_cache/*" "*/.ruff_cache/*" "*/.audit_cache/*" "*.zip" "*.tar" "*.gz" "*.tgz" ".env"
	@echo ""
	@echo "================================================================================"
	@echo "Created code.zip successfully."
	@echo "REMINDER: Export and submit root log.txt as chat_transcript and package"
	@echo "agent-trace.zip per agent_trace_instructions.md before final submission."
	@echo "Submission URL: https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists"
	@echo "================================================================================"

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .audit_cache sample_predictions.csv code.zip
