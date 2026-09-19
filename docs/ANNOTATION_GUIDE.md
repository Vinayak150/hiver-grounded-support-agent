# Human Annotation Guide

## Current status

Phase 2 created a blinded queue of 300 candidates. Phase 2.6 deterministically
froze exactly 200 final evaluation candidates: 160 representative and 40 challenge
cases. It also created 200 separate `AI_PROVISIONAL` suggestions to accelerate
later review. `golden_annotations.csv` now contains **200 human-entered, finalized
labels** created by the project author.

AI decision-support was used during part of the manual labeling process. Assistance
status was not recorded reliably per row, so the dataset does not claim that any
specific row was unaided or that the 200 rows are independent human judgments. The
dataset-level disclosure is
[`golden_annotation_provenance.md`](../data/annotations/golden_annotation_provenance.md).

The completed frozen-set review used:

```bash
make annotate-gold
```

The tool saves every decision atomically and resumes at the first unfinished case.
For a short sitting, use `python3 scripts/annotate.py --human-gold --limit 20`.
Check progress without entering review mode using:

```bash
python3 scripts/annotate.py --human-gold --progress
```

The CLI's human-gold mode does not display the stored AI provisional intent or action
before a row is saved. After the atomic save, it may report only whether intent/action
matched or differed from the separate stored suggestion; that comparison never edits
the row. This software-level blinding must not be interpreted as proof that the overall
annotation process was unaided, because AI decision-support was used during part of
manual labeling. The deprecated `--review-provisional` flag is a blind alias; bulk
acceptance is unavailable.

## What to label

Each case displays the sanitized customer message and customer-only context needed
to label the same request seen by the agent; historical Spotify replies are hidden.
Choose exactly one taxonomy intent and action, then record difficulty, optional risk
tags, and a short reason. Use `p` at the intent prompt to correct the previous saved
case, or `q` to stop safely. The CLI refuses duplicates and resumes automatically.

### `AUTO_HANDLE`

Use only when a grounded public response can be useful without private account
access, state changes, refund/payment processing, sensitive-data collection,
unsupported promises, or unavailable authoritative current-status information.

### `ESCALATE`

Use when the request needs private/internal action or when safe public evidence is
insufficient—for example compromise, ownership verification, account inspection,
billing/refund action, PII, outdated-policy risk, or unresolved ambiguity.

## Risk-tag vocabulary

| Tag | Apply when |
| --- | --- |
| `ACCOUNT_SPECIFIC` | The answer depends on one customer's account state. |
| `PAYMENT` | A charge or payment method is material. |
| `REFUND` | Refund eligibility or processing is requested. |
| `SECURITY` | Compromise, unauthorized access, or security is involved. |
| `PII` | Personal data is present or would need collection. |
| `POLICY_SENSITIVE` | A current authoritative policy is necessary. |
| `PRIVATE_LOOKUP` | Internal/private account lookup is required. |
| `MULTI_INTENT` | Multiple support needs cannot be reduced safely to one. |
| `AMBIGUOUS` | More context is required for a reliable interpretation. |
| `OUT_OF_DOMAIN` | The case is not a supported Spotify support request. |
| `DEVICE_CONTEXT` | Device/OS/integration details are necessary. |
| `LOW_CONTEXT` | The supplied text is too sparse for confident handling. |

## Integrity and versioning

Every finalized row records `annotation_source=human`, `annotator=candidate`, a
timezone-aware `reviewed_at` timestamp, taxonomy version `spotify-intents-v1`,
sampling version `spotify-golden-candidates-v1`, and split version
`spotify-temporal-v1`. The software cannot create a finalized row without explicit
interactive input. In this dataset, `annotation_source=human` establishes that the
human reviewer entered and finalized the stored decision. It does **not** establish
that the decision was independently or unaidedly produced. Because row-level
assistance provenance was not captured, the project does not retroactively classify
individual rows as assisted or unassisted.

The original 300-case queue remains provenance for the protected 200-case freeze.
The Phase 6B target was all 200 frozen cases even though the fail-closed minimum was
150. `make validate-gold` passed at 200/200 before the frozen evaluation was run.
Provisional-label distributions and the separate measured human–LLM agreement study
are not substitutes for the gold labels or final benchmark results.

Candidate text is historical public TWCS content, sanitized for URLs, handles,
email-like strings, and long numeric identifiers. It is committed only because the
author must see the cases and the assignment requires delivery of the eventual
evaluation set. It must not be repurposed as training or retrieval data.
