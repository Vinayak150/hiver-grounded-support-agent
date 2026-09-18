.PHONY: test lint plan profile spotify taxonomy splits annotation-queue annotate leakage-audit

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

spotify:
	python3 scripts/extract_spotify.py --input "$(TWCS_INPUT)"

splits:
	python3 scripts/create_splits.py

taxonomy:
	LOKY_MAX_CPU_COUNT=4 python3 scripts/explore_taxonomy.py

leakage-audit:
	python3 scripts/audit_leakage.py

annotation-queue:
	python3 scripts/build_annotation_queue.py

annotate:
	python3 scripts/annotate.py
