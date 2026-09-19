# Grounded Customer Support Agent

An independently implemented, evaluation-first support agent for the Hiver SDE Intern
assignment. The frozen brand is **SpotifyCares**. The project treats historical public
support replies as retrieval evidence—not as current policy, private account access, or
proof that an issue was resolved.

## Verified status

- Final candidate: `spotify-grounded-agent-v1.0-final-candidate`.
- Retained behavior: original Phase 4 (`configs/agent.yaml`).
- Phase 4.1 remediation: **REJECTED** and retained only for auditability.
- Frozen benchmark: 200 cases, 160 representative + 40 challenge, untouched.
- Human gold: 0; final evaluation is correctly blocked.
- Final headline: `PENDING_HUMAN_GOLD`.
- Human–LLM judge agreement: `NOT_YET_MEASURED`.

The architecture is:

```text
customer → intent classifier → risk detection → historical retrieval
         → evidence sufficiency → grounded response → verifier
         → AUTO_HANDLE or ESCALATE
```

Private, account-specific, payment, refund, security, current-policy, and weak-evidence
requests fail closed to escalation.

## Reviewer quickstart — under 15 minutes

Python 3.11+ is required. No raw TWCS data or API credentials are needed.

```bash
make setup
make demo
make test
make validate-submission
```

Expected local runtime is approximately 2–5 minutes after dependency download.
`make demo` uses explicitly synthetic, sanitized fixtures and prints the customer
message, predicted intent, retrieved evidence IDs, reply, action, and reason codes. It
is a structural smoke test—not benchmark evidence.

Key review artifacts:

- [Near-final report](docs/FINAL_REPORT.md)
- [Curated 15-decision log](docs/FINAL_DECISION_LOG.md)
- [Final-system manifest](data/manifests/final_system_manifest.json)
- [Phase 5B failure audit](docs/PHASE5B_FAILURE_AUDIT.md)
- [Top-five structured failures](results/top5_failure_modes.json)
- [Citations](CITATIONS.md)

## Current DEVELOPMENT diagnostics

### UNVALIDATED LLM-JUDGE DEVELOPMENT DIAGNOSTICS

| System | Derived overall pass rate |
| --- | ---: |
| Fixed always-escalate | 35.00% |
| Lexical neighbor | 26.25% |
| Original proposed agent | 22.50% |

These are not final benchmark, safety, superiority, or human-agreement claims. The
80-case Phase 5A cohort deliberately included all 65 proposed `AUTO_HANDLE` cases and
only 15 stratified escalations, so it is not a natural-prevalence estimate. The Groq
`openai/gpt-oss-20b` judge showed a 37.5% order-bias flip rate at N=8, and no human
agreement has been measured. Generic safe handoffs were sometimes rewarded.

Phase 4.1 was rejected after the resource-constrained 45-pair DEVELOPMENT comparison:
7 improved, 21 unchanged, 17 regressed, and critical failures increased from 3 to 5.

## Final evaluation gate

```bash
make validate-gold     # currently exits blocked: 0 genuine human rows
make final-eval        # calls the gate first and currently fails before prediction
make judge-agreement   # requires genuine finalized human rubric ratings
```

`validate-gold` requires 150–250 unique finalized human rows, valid taxonomy/action
values and reasons, membership in the frozen set, no TRAIN/DEVELOPMENT IDs, and no
provisional or unresolved records. `final-eval` then generates fixed, lexical, and
original Phase 4 predictions; computes intent/action metrics, bootstrap 95% intervals,
and per-intent/action slices; and requires human response-quality evidence before
publishing Correct & Safe Automation Coverage. It never substitutes provisional labels.

## What is included

```text
configs/       versioned taxonomy, baseline, agent, judge, and freeze settings
data/          tracked manifests/annotation contracts; ignored raw and processed text
docs/          architecture, safety, protocols, failure audit, and final report
results/       reproducible DEVELOPMENT diagnostics and audits
scripts/       profiling, annotation, agent, judge, gate, demo, and validator commands
src/           deterministic pipeline and metric implementations
tests/         leakage, schema, statistics, agent, and submission-gate tests
```

The raw dataset and reconstructed corpus are intentionally untracked. Committed results
can be reviewed without rerunning expensive provider calls.

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

5. Optional provider-backed DEVELOPMENT diagnostics, when credentials and quota are
   available:

   ```bash
   make judge-v2-prepare
   make judge-v2
   make judge-v2-analyze
   ```

The judge commands are not required to inspect the submission; their validated cached
artifacts are committed. They must never be rerun against the frozen benchmark.

## Data and evaluation provenance

The source export has 2,811,774 rows. Spotify extraction produced 28,277 usable threads.
After later-split decontamination, the protected chronological split contains 19,793
TRAIN, 2,594 DEVELOPMENT, and 2,619 GOLDEN_CANDIDATE threads, with zero exact or detected
near-duplicate cross-split collisions under the declared audit thresholds.

The frozen evaluation manifest was created before final-system evaluation. Separate
`AI_PROVISIONAL` suggestions may assist future human review but are neither gold nor
agreement evidence. The final annotation CSV remains header-only until a human performs
the work.

## Integrity commitments

- Final metrics and human–LLM agreement will be measured, not fabricated.
- Model development uses TRAIN/DEVELOPMENT only; frozen IDs are excluded from training,
  retrieval, examples, calibration, and remediation.
- Every published result must point to versioned code, input hashes, and an explicit
  evidence source.
- Historical support language cannot authorize private action or current policy claims.
- Engineering readiness and final-evaluation readiness are reported separately.

See [the evaluation protocol](docs/EVALUATION_PROTOCOL.md),
[annotation guide](docs/ANNOTATION_GUIDE.md), [agent architecture](docs/AGENT_ARCHITECTURE.md),
and [safety policy](docs/SAFETY_POLICY.md) for detailed contracts.
