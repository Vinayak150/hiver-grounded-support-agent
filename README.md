# Grounded Customer Support Agent

An independently implemented, evaluation-first support agent for the Hiver SDE Intern
assignment. The frozen brand is **SpotifyCares**. Historical public support replies are
treated as retrieval evidence—not as current policy, private account access, or proof
that an issue was resolved.

## Verified final status

- Final candidate: `spotify-grounded-agent-v1.0-final-candidate`.
- Retained behavior: original Phase 4 (`configs/agent.yaml`).
- Phase 4.1 remediation: **REJECTED** and retained only for auditability.
- Frozen benchmark: **200 human-finalized cases**, 160 representative + 40 challenge.
- Gold-label provenance: one human reviewer entered the final decisions, with AI
  decision-support used during part of labeling; these are not claimed as 200
  independent unaided human judgments.
- Final evaluation: **COMPLETE** without retraining, threshold changes, or prediction changes.
- Human response-quality review: complete for all five proposed final `AUTO_HANDLE` cases.
- Human–LLM judge agreement: **MEASURED on 40 blinded ratings**.
- Headline intent result: proposed macro-F1 **0.497453**, bootstrap 95% CI
  **[0.424263, 0.561594]**.
- Automation result: **2.5% coverage** and **0% correct-and-safe automation coverage**.

The proposed intent classifier beats both baselines on the frozen set. The end-to-end
agent does **not** beat both baselines overall: it escalates almost everything, still
misses four required escalations, and has no correct-and-safe automated response.

The architecture is:

```text
customer → intent classifier → risk detection → historical retrieval
         → evidence sufficiency → grounded response → verifier
         → AUTO_HANDLE or ESCALATE
```

Private, account-specific, payment, refund, security, current-policy, and weak-evidence
requests fail closed to escalation.

## Reviewer quickstart — under 15 minutes

Python 3.11+ is required. No raw TWCS data or API credentials are needed to inspect the
recorded artifacts.

```bash
make setup
make demo
make test
make validate-submission
```

`make demo` uses explicitly synthetic, sanitized fixtures. It is a structural smoke
test—not benchmark evidence. The frozen benchmark should not be rerun or used for
tuning; inspect its recorded result instead.

Key review artifacts:

- [Final report](docs/FINAL_REPORT.md)
- [Frozen benchmark comparison](results/final/comparison.json)
- [Measured human–LLM agreement](results/human_judge_agreement.json)
- [Gold annotation provenance disclosure](data/annotations/golden_annotation_provenance.md)
- [Curated 15-decision log](docs/FINAL_DECISION_LOG.md)
- [Final-system manifest](data/manifests/final_system_manifest.json)
- [Phase 5B failure audit](docs/PHASE5B_FAILURE_AUDIT.md)
- [LLM judge protocol](docs/LLM_JUDGE_PROTOCOL.md)
- [Top-five structured failures](results/top5_failure_modes.json)
- [Citations](CITATIONS.md)

## Frozen final benchmark — N=200

### Intent classification

| System | Accuracy | Macro-F1 | Weighted-F1 | Macro-F1 bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Fixed | 0.120 | 0.023810 | 0.025714 | [0.015504, 0.031474] |
| Lexical | 0.375 | 0.383998 | 0.373679 | [0.310644, 0.448291] |
| Proposed | **0.510** | **0.497453** | **0.510869** | **[0.424263, 0.561594]** |

### Action and automation

| System | Automation coverage | Escalation recall | False escalation | Missed escalation | Unsafe auto-handle |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed | 0.000 | 1.000000 | 1.000000 | 0.000000 | 0.000000* |
| Lexical | 0.165 | 0.877778 | 0.800000 | 0.122222 | 0.333333 |
| Proposed | **0.025** | 0.955556 | **0.990909** | 0.044444 | **0.800000** |

`*` Fixed automated no cases, so the zero unsafe-auto value has a zero denominator.

The proposed confusion counts are 109 false escalations, 4 missed escalations, 1 safe
auto-handle, and 86 true escalations. It escalated **195/200** cases and auto-handled
only **5/200**. Only **1/5** automation decisions aligned with the gold `AUTO_HANDLE`
action, and human response-quality review reduced Correct-and-Safe Automation Coverage
to **0/200 (0%)**. This is strongly conservative behavior, but it is also materially
miscalibrated and not deployment-ready.

## Human–LLM agreement — N=40 blinded ratings

Binary overall-pass exact agreement is **0.70**. The confusion table is:

| Human rating | LLM false | LLM true |
| --- | ---: | ---: |
| Human false | 25 | 9 |
| Human true | 3 | 3 |

| Dimension | Exact | Within one | Weighted kappa | Spearman |
| --- | ---: | ---: | ---: | ---: |
| Groundedness | 0.225 | 0.425 | 0.059266 | 0.108062 |
| Relevance | 0.275 | 0.475 | 0.150693 | 0.249904 |
| Helpfulness | 0.300 | 0.525 | 0.120073 | 0.054332 |
| Safety | 0.925 | 0.975 | 0.000000 | 0.000000 |
| Brand/context | 0.225 | 0.550 | -0.039326 | -0.185186 |

Agreement is weak or limited on most ordinal dimensions. Safety's 92.5% exact agreement
is not evidence of validated safety agreement: weighted kappa and Spearman are both
zero, consistent with low score variance or a prevalence effect. The LLM judge remains
a DEVELOPMENT diagnostic, not a substitute for human evaluation.

## DEVELOPMENT diagnostics

### UNVALIDATED LLM-JUDGE DEVELOPMENT DIAGNOSTICS

| System | Derived overall pass rate |
| --- | ---: |
| Fixed always-escalate | 35.00% |
| Lexical neighbor | 26.25% |
| Original proposed agent | 22.50% |

These are not final benchmark, safety, or superiority claims. The 80-case Phase 5A
cohort deliberately included all 65 proposed DEVELOPMENT `AUTO_HANDLE` cases and only
15 stratified escalations, so it is not a natural-prevalence estimate. The Groq
`openai/gpt-oss-20b` judge showed a 37.5% order-bias flip rate at N=8. Its later blinded
human agreement was only 70% on overall pass and weak on most ordinal dimensions.

Phase 4.1 was rejected after a resource-constrained 45-pair DEVELOPMENT comparison:
7 improved, 21 unchanged, 17 regressed, and critical failures increased from 3 to 5.

## Evaluation provenance

The source export has 2,811,774 rows. Spotify extraction produced 28,277 usable threads.
After later-split decontamination, the protected chronological split contains 19,793
TRAIN, 2,594 DEVELOPMENT, and 2,619 GOLDEN_CANDIDATE threads, with zero exact or detected
near-duplicate cross-split collisions under the declared audit thresholds.

The 200-case evaluation set was frozen before final-system evaluation. A single human
reviewer entered and finalized all 200 stored decisions, but AI decision-support was
used during part of the manual labeling process. Per-row assistance status was not
recorded, so no individual row is claimed to be unaided. In this dataset,
`annotation_source=human` means the final stored decision was human-entered and
finalized; it does not establish independent unaided annotation. See the
[dataset-level provenance disclosure](data/annotations/golden_annotation_provenance.md).

The five proposed automated replies received separate human response-quality judgments.
The 40 human judge ratings were selected by a fixed hash rule and collected blind to
system identity and LLM results.

The final benchmark is modest and deliberately challenge-enriched rather than a natural
production-prevalence sample. Human action labels are subjective and were partly produced
with AI decision-support; response-quality judgments are also subjective. Historical
Twitter replies may not represent current Spotify policies. See the
[final report](docs/FINAL_REPORT.md#8-what-is-misleading-about-my-headline-number) for
the complete interpretation limits.

## What is included

```text
configs/       versioned taxonomy, baseline, agent, judge, and freeze settings
data/          tracked manifests/annotation contracts; ignored raw and processed text
docs/          architecture, safety, protocols, failure audit, and final report
results/       frozen benchmark plus reproducible DEVELOPMENT diagnostics and audits
scripts/       profiling, annotation, agent, judge, gate, demo, and validator commands
src/           deterministic pipeline and metric implementations
tests/         leakage, schema, statistics, agent, and submission-gate tests
```

The raw dataset and reconstructed corpus are intentionally untracked. Recorded results
can be reviewed without rerunning provider calls or the frozen benchmark.

## Full data reproduction

1. Download **Customer Support on Twitter (TWCS)** from the credited
   [Kaggle source](https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter).
2. Place the export at `data/raw/twcs.csv`.
3. Verify SHA-256:

   ```bash
   shasum -a 256 data/raw/twcs.csv
   # cd297fcfa1bf6f99938be242e8e578980bc6d1b96adc8691abec9a39175b03c0
   ```

4. Rebuild the data and DEVELOPMENT systems:

   ```bash
   make profile
   make spotify
   make splits
   make taxonomy
   make leakage-audit
   make annotation-queue
   make freeze-evaluation
   make provisional-labels
   make provisional-audit
   make baselines-dev
   make train-agent
   make agent-dev
   ```

5. The provider-backed DEVELOPMENT judge commands are not required to inspect the
   submission. Their cached, validated artifacts are preserved for auditability and
   must not be treated as human truth or rerun against the frozen benchmark.

## Integrity commitments

- Model development used TRAIN/DEVELOPMENT only; frozen IDs were excluded from training,
  retrieval, examples, calibration, and remediation.
- The final results were measured from human-finalized gold and response-quality review.
  The gold-label provenance disclosure records that AI decision-support was used during
  part of labeling; `annotation_source=human` does not imply unaided independence.
- No model, threshold, prediction, or retained-system decision was changed from final-set
  results.
- Every published result points to versioned code, input hashes, and an explicit evidence
  source.
- Historical support language cannot authorize private action or current policy claims.
- Intent-classification improvement is reported separately from automation quality.

See [the evaluation protocol](docs/EVALUATION_PROTOCOL.md),
[annotation guide](docs/ANNOTATION_GUIDE.md), [agent architecture](docs/AGENT_ARCHITECTURE.md),
and [safety policy](docs/SAFETY_POLICY.md) for detailed contracts.
