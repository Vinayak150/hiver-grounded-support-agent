.PHONY: setup test lint plan profile spotify taxonomy splits annotation-queue annotate leakage-audit freeze-evaluation provisional-labels provisional-audit phase2-6 baselines-dev train-agent agent-dev judge-prepare judge-dev judge-analyze judge-v2-prepare judge-v2 judge-v2-analyze final-system demo validate-gold final-eval judge-agreement validate-submission

TWCS_INPUT ?= data/raw/twcs.csv
PROFILE_CONFIG ?= configs/profiling.yaml

setup:
	python3 -m pip install -e '.[dev]'

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
	python3 scripts/annotate.py --review-provisional

freeze-evaluation:
	python3 scripts/freeze_evaluation_set.py

provisional-labels:
	python3 scripts/generate_provisional_labels.py

provisional-audit:
	python3 scripts/audit_provisional_labels.py

phase2-6: freeze-evaluation provisional-labels provisional-audit

baselines-dev:
	python3 scripts/run_baselines.py

train-agent:
	python3 scripts/train_intent_classifier.py

agent-dev:
	python3 scripts/run_agent.py

judge-prepare:
	python3 scripts/run_judge.py --prepare-only

judge-dev:
	python3 scripts/run_judge.py

judge-analyze:
	python3 scripts/analyze_judge.py

judge-v2-prepare:
	python3 scripts/run_judge_v2.py --prepare-only

judge-v2:
	python3 scripts/run_judge_v2.py

judge-v2-analyze:
	python3 scripts/analyze_judge_v2.py

final-system:
	python3 scripts/build_final_system_manifest.py

demo:
	python3 scripts/run_demo.py

validate-gold:
	python3 scripts/validate_gold.py

final-eval: validate-gold
	python3 scripts/run_final_evaluation.py

judge-agreement:
	python3 scripts/run_judge_agreement.py

validate-submission:
	python3 scripts/validate_submission.py --run-tests
