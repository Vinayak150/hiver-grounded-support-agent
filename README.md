# Grounded Customer Support Agent

An independently implemented, evaluation-first customer-support agent for the Hiver SDE Intern take-home assignment.

## Current status

**Phase 2.6 evaluation set frozen; human confirmation is pending.** Phase 1.5 froze `SpotifyCares` as the final brand. Phase 2 reconstructed 28,277 usable Spotify support threads, produced leakage-clean chronological splits, explored a nine-intent train-only taxonomy, and prepared a 300-item candidate queue. Phase 2.6 deterministically froze 200 evaluation cases (160 representative, 40 challenge), protected their IDs, and generated 200 separately stored `AI_PROVISIONAL` suggestions. The golden annotation file intentionally contains zero finalized rows. No benchmark, model, retrieval index, human-agreement claim, or headline performance/safety metric exists yet.

Two external repositories supplied as architectural references were reviewed at a high level. No source code, labels, results, prompts, or evaluation artifacts were copied. See [CITATIONS.md](CITATIONS.md).

## Intended workflow

```text
Dataset profiling → brand selection → thread-safe splits → human gold set
→ baselines → grounded pipeline → safety gates → frozen evaluation → report
```

The core safety constraint is that historical support replies are evidence of past brand behaviour, not a source of current policy or factual truth. Requests needing private, account-specific, payment, security, or policy-sensitive action must default toward escalation.

## Repository layout

```text
configs/       versioned configuration and frozen evaluation manifests
data/          ignored source/processed text; tracked manifests and annotation queue
docs/          plans, decision log, annotation protocol, and final report
evaluation/    evaluation harness (not implemented yet)
results/       profiling, audit, and train-only taxonomy artifacts
scripts/       reproducible profiling, extraction, split, audit, and annotation commands
src/           installable data, taxonomy, and annotation modules
tests/         deterministic data-engineering and annotation-integrity tests
```

## Commands available now

```bash
python3 -m pip install -e '.[dev]'
make test     # run data-engineering unit tests and lint checks
make plan     # print the phased plan location
make profile  # profile the local, ignored data/raw/twcs.csv export
make spotify  # reconstruct SpotifyCares threads from the raw export
make splits   # create deterministic chronological train/dev/golden-candidate splits
make taxonomy # explore train-only clusters and lexical taxonomy signals
make leakage-audit    # independently verify protected-split leakage constraints
make annotation-queue # build the deterministic 300-item annotation queue
make freeze-evaluation # freeze the protected 160/40 final candidate set
make provisional-labels # create separate AI_PROVISIONAL suggestions
make provisional-audit  # audit provisional distributions and contradictions
make phase2-6          # regenerate the three Phase 2.6 artifacts above
make annotate          # explicitly accept/correct suggestions as a human
```

`make reproduce`, `make demo`, and `make rebuild` will be added only when their inputs, outputs, and claims can be made reproducible.

## Reproducible artifacts

The Phase 1 run used `make profile` with `data/raw/twcs.csv`. Its aggregate artifacts are [the raw-data manifest](data/manifests/twcs_manifest.json), [candidate CSV](results/brand_profile.csv), [candidate JSON](results/brand_profile.json), and [ID-only heuristic review sample](results/heuristic_validation.json). Phase 1.5 adds [the saturated audit result](results/brand_selection_audit.json) and [ID-only diagnostic labels](data/annotations/brand_audit.csv).

Phase 2 adds the [Spotify extraction manifest](data/manifests/spotify_threads_manifest.json), [split manifest](data/manifests/split_manifest.json), [independent leakage audit](data/manifests/leakage_audit.json), [train-only taxonomy exploration](results/taxonomy_exploration.json), [300-item golden-candidate queue](data/annotations/golden_candidates.csv), and a resumable [human annotation file](data/annotations/golden_annotations.csv). The extraction yielded 28,277 usable threads. After later-split decontamination, the frozen split contains 19,793 train, 2,594 dev, and 2,619 golden-candidate threads, with zero exact or detected near-duplicate cross-split collisions in the independent audit.

Phase 2.6 adds the [final 200-case manifest](data/manifests/final_golden_candidate_manifest.json), [unlabeled frozen cases](data/annotations/final_golden_candidates.csv), separate [AI provisional suggestions](data/annotations/ai_provisional_labels.csv), and [provisional audit](results/provisional_label_audit.json). These suggestions are review aids, never gold labels. The annotation file currently contains **0 human labels**, and `GOLDEN_SET_STATUS` remains `AWAITING_HUMAN_CONFIRMATION` until at least 150 cases are explicitly confirmed by the author.

The raw TWCS export and reconstructed thread JSONL remain ignored and uncommitted. See [the split protocol](docs/SPLIT_PROTOCOL.md), [taxonomy](docs/TAXONOMY.md), and [annotation guide](docs/ANNOTATION_GUIDE.md) for definitions and limitations. No final model or evaluation metric exists yet.

## Integrity commitments

- Human labels and human-vs-LLM agreement will be collected, not fabricated. Model development may use TRAIN/DEVELOPMENT only; final evaluation remains blocked until at least 150 frozen cases are explicitly human-confirmed.
- Splits will occur by reconstructed conversation/thread, never individual tweet.
- Evaluation data will be excluded from retrieval, training, few-shot examples, and threshold tuning; automated checks will enforce this.
- Every reported number will be generated by versioned code and traceable inputs.
- Remote LLM outputs used for headline results will be cached with model and prompt metadata.

See [docs/PHASED_IMPLEMENTATION_PLAN.md](docs/PHASED_IMPLEMENTATION_PLAN.md) for the full plan and [docs/DATA_PROFILING_REQUIREMENTS.md](docs/DATA_PROFILING_REQUIREMENTS.md) for the minimum Phase 1 inputs.
