PY := .venv/bin/python

.PHONY: test eval run lint format

test:
	$(PY) -m pytest

eval:
	$(PY) -m tests.eval.run_eval

run:
	$(PY) -m uvicorn app.api.main:app --reload

lint:
	.venv/bin/ruff check app tests

format:
	.venv/bin/ruff format app tests
