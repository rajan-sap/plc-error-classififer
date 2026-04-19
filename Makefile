.PHONY: install run test smoke eval verify clean

install:
	pip install -r requirements.txt

run:
	uvicorn src.api.main:app --reload --port 8000

test:
	pytest

smoke:
	python scripts/smoke.py

eval:
	python -m src.eval.runner

# One command for a reviewer: install dependencies, run the test suite,
# run the end-to-end smoke (mock + live LLM if a key is set), regenerate
# the eval report. If all four steps succeed, the system works.
# (Windows reviewers without GNU Make: run `python scripts/verify.py` instead.)
verify: install
	python scripts/verify.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__
