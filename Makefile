.PHONY: test lint plan

test: lint
	python3 -m pytest

lint:
	python3 -m ruff check .

plan:
	@echo "See docs/PHASED_IMPLEMENTATION_PLAN.md"
