# Grounded Customer Support Agent

An independently implemented, evaluation-first customer-support agent for the Hiver SDE Intern take-home assignment.

## Current status

**Phase 5A quota-safe LLM-judge DEVELOPMENT diagnostics are complete.** Protocol V2 uses Groq `openai/gpt-oss-20b` consistently across an 80-case shared cohort containing all 65 proposed `AUTO_HANDLE` cases. The incomplete 120B pilot is preserved but excluded. These are unvalidated LLM-judge diagnostics—not final benchmark, safety, superiority, or human-agreement claims. Phase 2.6's frozen 200 cases remain untouched and human confirmation remains at zero.

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
results/       profiling, audits, taxonomy, and DEVELOPMENT baseline artifacts
scripts/       reproducible data, annotation, and baseline commands
src/           data, agent, retrieval, generation, baseline, and evaluation modules
tests/         deterministic data, leakage, agent, metric, and statistics tests
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
make baselines-dev     # generate both DEVELOPMENT-only baseline artifacts
make train-agent       # verify TRAIN-only intent-classifier fitting
make agent-dev         # generate proposed-agent DEVELOPMENT artifacts
make judge-prepare     # create the protected 200-case DEVELOPMENT judge sample
make judge-dev         # run real judging; requires configured provider credentials
make judge-analyze     # analyze completed real judge results
make judge-v2-prepare  # build the protected 80-case quota-safe sample
make judge-v2          # run the isolated Groq 20B V2 protocol
make judge-v2-analyze  # analyze complete V2 outputs
```

`make reproduce`, `make demo`, and `make rebuild` will be added only when their inputs, outputs, and claims can be made reproducible.

## Reproducible artifacts

The Phase 1 run used `make profile` with `data/raw/twcs.csv`. Its aggregate artifacts are [the raw-data manifest](data/manifests/twcs_manifest.json), [candidate CSV](results/brand_profile.csv), [candidate JSON](results/brand_profile.json), and [ID-only heuristic review sample](results/heuristic_validation.json). Phase 1.5 adds [the saturated audit result](results/brand_selection_audit.json) and [ID-only diagnostic labels](data/annotations/brand_audit.csv).

Phase 2 adds the [Spotify extraction manifest](data/manifests/spotify_threads_manifest.json), [split manifest](data/manifests/split_manifest.json), [independent leakage audit](data/manifests/leakage_audit.json), [train-only taxonomy exploration](results/taxonomy_exploration.json), [300-item golden-candidate queue](data/annotations/golden_candidates.csv), and a resumable [human annotation file](data/annotations/golden_annotations.csv). The extraction yielded 28,277 usable threads. After later-split decontamination, the frozen split contains 19,793 train, 2,594 dev, and 2,619 golden-candidate threads, with zero exact or detected near-duplicate cross-split collisions in the independent audit.

Phase 2.6 adds the [final 200-case manifest](data/manifests/final_golden_candidate_manifest.json), [unlabeled frozen cases](data/annotations/final_golden_candidates.csv), separate [AI provisional suggestions](data/annotations/ai_provisional_labels.csv), and [provisional audit](results/provisional_label_audit.json). These suggestions are review aids, never gold labels. The annotation file currently contains **0 human labels**, and `GOLDEN_SET_STATUS` remains `AWAITING_HUMAN_CONFIRMATION` until at least 150 cases are explicitly confirmed by the author.

The raw TWCS export and reconstructed thread JSONL remain ignored and uncommitted. See [the split protocol](docs/SPLIT_PROTOCOL.md), [taxonomy](docs/TAXONOMY.md), and [annotation guide](docs/ANNOTATION_GUIDE.md) for definitions and limitations. No final model or reported gold-dependent evaluation metric exists yet.

Phase 3 adds deterministic DEVELOPMENT predictions for the [fixed baseline](results/dev_baseline_fixed.jsonl) and [lexical baseline](results/dev_baseline_lexical.jsonl), plus a [generation manifest](results/dev_baseline_manifest.json). The metric library is implemented but no gold-dependent metric has been computed. See [baseline documentation](docs/BASELINES.md) and the [evaluation protocol](docs/EVALUATION_PROTOCOL.md).

Phase 4 adds 2,594 deterministic DEVELOPMENT predictions for the proposed agent,
plus its traceability manifest and unlabeled engineering diagnostics. The current
run allows 65 cases through every automation gate and escalates 2,529; these are
coverage diagnostics, not correctness or safety measurements. See the
[agent architecture](docs/AGENT_ARCHITECTURE.md) and
[safety policy](docs/SAFETY_POLICY.md). Regenerate with `make agent-dev`.

Phase 5A adds a blinded, schema-validated OpenAI-compatible judge adapter,
content-addressed caching, repeatability/order-bias experiments, descriptive
analysis, and future human-agreement utilities. The 120B V1 pilot stopped at
313/880 because of Groq quota and is excluded from comparison. The predeclared
[V2 sample](results/dev_judge_v2_sample_manifest.json) contains 80 shared
DEVELOPMENT cases—all 65 proposed `AUTO_HANDLE` cases plus 15 deterministic
stratified `ESCALATE` cases. V2 uses only `openai/gpt-oss-20b`; its
[summary](results/dev_judge_v2_summary.json) is explicitly labeled unvalidated.
See the [rubric](docs/LLM_JUDGE_RUBRIC.md) and
[protocol](docs/LLM_JUDGE_PROTOCOL.md). Human agreement remains unmeasured.

## Integrity commitments

- Human labels and human-vs-LLM agreement will be collected, not fabricated. Model development may use TRAIN/DEVELOPMENT only; final evaluation remains blocked until at least 150 frozen cases are explicitly human-confirmed.
- Splits will occur by reconstructed conversation/thread, never individual tweet.
- Evaluation data will be excluded from retrieval, training, few-shot examples, and threshold tuning; automated checks will enforce this.
- Every reported number will be generated by versioned code and traceable inputs.
- Remote LLM outputs used for headline results will be cached with model and prompt metadata.

See [docs/PHASED_IMPLEMENTATION_PLAN.md](docs/PHASED_IMPLEMENTATION_PLAN.md) for the full plan and [docs/DATA_PROFILING_REQUIREMENTS.md](docs/DATA_PROFILING_REQUIREMENTS.md) for the minimum Phase 1 inputs.
