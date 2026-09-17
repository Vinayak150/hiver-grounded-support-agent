# Phased implementation plan

## Phase 0 — repository integrity and experiment contract

- **Objective:** Establish a reproducible repository boundary without claiming unmeasured results.
- **Files:** `README.md`, `CITATIONS.md`, `DECISION_LOG.md`, `docs/`, `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml`.
- **Inputs:** Assignment brief and permitted architectural references.
- **Outputs:** Repository scaffold, explicit integrity commitments, and this plan.
- **Invariants:** No copied source/artifacts; no fabricated measurements; no substantive agent implementation.
- **Tests:** Packaging/import smoke test, lint, and documentation-link check in CI.
- **Exit criteria:** Clean clone passes `make test`; all early decisions are marked provisional where data-dependent.
- **Complexity:** Low.
- **Dependencies:** None.

## Phase 1 — dataset profiling and evidence-based brand choice

- **Objective:** Reconstruct conversations from TWCS and compare candidate brands using measured, reproducible viability signals.
- **Files:** `scripts/profile_dataset.py`, `src/support_agent/data/`, `configs/profiling.yaml`, `results/brand_profile.*`, `docs/BRAND_SELECTION.md`.
- **Inputs:** Raw TWCS export with lineage/order fields and a versioned sampling manifest.
- **Outputs:** Schema report, malformed-thread analysis, candidate-brand comparison, and documented brand decision.
- **Invariants:** Thread-level reconstruction; raw data remains unmodified; no evaluation examples selected yet; every result points to a source manifest.
- **Tests:** Linkage integrity, duplicate-ID, inbound/outbound, ordering, and deterministic-sampling tests.
- **Exit criteria:** One brand chosen from measured signals, with caveats and rerunnable profiling command.
- **Complexity:** Medium.
- **Dependencies:** Phase 0; dataset access.

## Phase 2 — taxonomy, split contract, and human annotation protocol

- **Objective:** Derive a compact brand-specific intent taxonomy and create isolated train/development/golden partitions.
- **Files:** `docs/ANNOTATION_GUIDE.md`, `data/manifests/`, `scripts/create_splits.py`, `configs/splits.yaml`, `tests/test_leakage.py`.
- **Inputs:** Chosen-brand threads and Phase 1 profiling artifacts.
- **Outputs:** Taxonomy rationale, thread-level split manifests, annotation instructions, and a sampling queue for 150–250 author-labelled cases.
- **Invariants:** Golden examples are human-labelled, held out by thread, and never used in retrieval/training/few-shot/threshold calibration; challenge cases are flagged rather than oversampled invisibly.
- **Tests:** Cross-split thread leakage, duplicate/near-duplicate leakage, stable split seed, manifest count, and provenance tests.
- **Exit criteria:** Annotation protocol completed and auditable; golden set exists only after the author labels it.
- **Complexity:** High.
- **Dependencies:** Phase 1 and author time for labels.

## Phase 3 — transparent baselines and measurement primitives

- **Objective:** Implement two explicit comparison baselines and metrics without tuning on golden labels.
- **Files:** `src/support_agent/baselines/`, `evaluation/metrics.py`, `evaluation/bootstrap.py`, `evaluation/run_baselines.py`, `tests/test_metrics.py`.
- **Inputs:** Train/development manifests and human-labelled golden set after completion.
- **Outputs:** Majority/trivial and simple retrieval/classification baseline outputs, confusion matrices, escalation metrics, and confidence-interval utilities.
- **Invariants:** Development-only threshold selection; metrics retain denominators; no quality metric is mislabeled as production safety.
- **Tests:** Hand-computed metric fixtures, bootstrap seed determinism, zero-denominator behavior, and split-guard tests.
- **Exit criteria:** Baselines run from frozen manifests and produce only computed results.
- **Complexity:** Medium.
- **Dependencies:** Phase 2.

## Phase 4 — grounded support pipeline and conservative safety policy

- **Objective:** Build the independently authored intent, retrieval, evidence-compatibility, reply, verification, and escalation components.
- **Files:** `src/support_agent/{intent,retrieval,generation,safety,schemas}.py`, `configs/pipeline.yaml`, `scripts/run_demo.py`.
- **Inputs:** Development corpus, selected taxonomy, model/API configuration, and safety rules derived from documented analysis.
- **Outputs:** Structured result containing intent, retrieved provenance, draft reply, action, and machine-readable reason.
- **Invariants:** Generated reply claims trace to retrieved evidence; sensitive/account-specific/low-evidence cases escalate; no answer treats historical text as current policy.
- **Tests:** PII, security, payment, account-action, out-of-domain, weak-retrieval, and provenance regression tests.
- **Exit criteria:** End-to-end smoke cases show audit trails and fail closed on unsafe/unsupported conditions.
- **Complexity:** High.
- **Dependencies:** Phases 1–3.

## Phase 5 — LLM-as-a-judge and human-agreement study

- **Objective:** Measure reply quality with an actual LLM judge and compare it with independent human ratings.
- **Files:** `evaluation/judge.py`, `configs/judge_rubric.yaml`, `data/annotations/`, `evaluation/agreement.py`, `docs/JUDGE_PROTOCOL.md`.
- **Inputs:** Frozen system replies, real human ratings on a predefined random subset, judge model/API configuration.
- **Outputs:** Cached judge records, rubric scores, human ratings, agreement statistics, and disagreement analysis.
- **Invariants:** Judge is an LLM rather than a deterministic proxy; prompt/model/version recorded; humans do not see judge scores; agreement is computed only from collected ratings.
- **Tests:** Cache-key, schema-validation, blinded-sampling, agreement-fixture, and no-missing-rating tests.
- **Exit criteria:** Actual judge/human agreement is reported with sample size and limitations—or transparently reported as unavailable.
- **Complexity:** High.
- **Dependencies:** Phases 2 and 4; human-rating collection and LLM access.

## Phase 6 — frozen evaluation, report, and reproducibility release

- **Objective:** Freeze inputs and produce an honest, reproducible submission.
- **Files:** `configs/evaluation_frozen.yaml`, `evaluation/run_final.py`, `results/`, `docs/TECHNICAL_REPORT.md`, `Makefile`, `Dockerfile` (if justified).
- **Inputs:** Locked golden set, development-selected configuration, cached judge outputs, and system predictions.
- **Outputs:** Headline metric with bootstrap intervals, slice analyses, two-baseline comparison, five real failure modes, decision log, and one-week plan.
- **Invariants:** No final-test tuning; all numbers regenerated by code; report states limitations, especially what is misleading about the headline number.
- **Tests:** Reproduction smoke test, frozen-artifact checksum test, report-reference check, and full CI.
- **Exit criteria:** `make reproduce` completes within 15 minutes from documented frozen artifacts; README directs a reviewer through results and limitations.
- **Complexity:** Medium–High.
- **Dependencies:** All prior phases.

## High-risk routes to misleading evaluation

1. Splitting individual tweets instead of threads and leaking conversation context.
2. Letting golden examples enter retrieval, prompt examples, training, or threshold tuning.
3. Calling LLM-generated labels “human labels.”
4. Replacing an LLM judge with deterministic heuristics while presenting it as LLM-as-a-judge.
5. Reporting judge/human agreement without collected, blinded human ratings.
6. Choosing the brand or taxonomy based on final-golden performance.
7. Measuring a low unsafe-auto rate over all tickets and hiding abstention or missed-escalation rates.
8. Treating historical support replies as live policy or factual verification.
9. Reporting performance without denominators, confidence intervals, slice sizes, or failure examples.
10. Comparing an optimized system with weakly specified or differently resourced baselines.

## Decisions that must wait for real profiling

- Selected brand and any claim about its conversation quality.
- Intent taxonomy labels and class count.
- Reconstruction rules for branching, missing, and multi-agent threads.
- Train/development/golden sampling strata and split proportions.
- Retrieval unit, corpus filters, and similarity cutoffs.
- Whether lexical, embedding, or hybrid retrieval is justified.
- Escalation thresholds and risk rules beyond universally conservative guards.
- Prompt structure, model provider, and caching strategy.
- Headline metric threshold/definition details and robustness slices.
