.PHONY: test lint plan profile

TWCS_INPUT ?= data/raw/twcs.csv
PROFILE_CONFIG ?= configs/profiling.yaml

test: lint
	python3 -m pytest

lint:
	python3 -m ruff check .

plan:
	@echo "See docs/PHASED_IMPLEMENTATION_PLAN.md"

profile:
	python3 scripts/profile_dataset.py --input "$(TWCS_INPUT)" --config "$(PROFILE_CONFIG)"
