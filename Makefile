# Makefile — common dev loops for the RCA agent.
# Uses the project venv at .venv (Python 3.12). `python` is NOT on PATH here.

PY := .venv/bin/python
PKG := src/rca_agent tests

.PHONY: help check test lint fmt eval install clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

check: lint test  ## Lint + run the full test suite (the pre-commit gate)

test:  ## Run the full test suite
	$(PY) -m pytest -q

lint:  ## Ruff static checks
	$(PY) -m ruff check .

fmt:  ## Ruff autofix (imports, simple issues)
	$(PY) -m ruff check --fix .

eval:  ## Run the fault-injection accuracy harness (writes eval/results/)
	$(PY) -m rca_agent.eval

install:  ## Install the package (editable) with dev+cluster+viz+rag+pptx extras
	$(PY) -m pip install -e '.[dev,cluster,viz,rag,pptx]'

clean:  ## Remove caches and build artifacts (keeps dist/ packages)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache *.egg-info src/*.egg-info 2>/dev/null || true
