# Human Annotation Guide

## Current status

Phase 2 created a blinded queue of 300 candidates: 240 representative cases and 60
challenge cases. `golden_annotations.csv` contains a header and **zero finalized
labels**. Only the project author should create rows through the local CLI.

Start with a 20-case pilot using the exact command:

```bash
python3 scripts/annotate.py --limit 20
```

Review pilot boundary problems before continuing, but do not inspect model results
or final-golden performance. Resume with `make annotate`; see progress with:

```bash
python3 scripts/annotate.py --progress
```

## What to label

Each case displays a sanitized customer message and up to six recent conversation
turns. Choose exactly one taxonomy intent, one action, one difficulty, optional
risk tags, and a short action reason. Defer rather than guess when context is
insufficient. The CLI saves each finalized case atomically, refuses duplicate case
IDs, and resumes at the first unfinished case.

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

Every finalized row records `annotation_source=human`, taxonomy version
`spotify-intents-v1`, sampling version `spotify-golden-candidates-v1`, and split
version `spotify-temporal-v1`. The software cannot create a finalized row without
explicit interactive input. Candidate proxy fields are not shown as intent/action
suggestions, and no machine suggestion is saved beside the annotation.

The 300-case queue is larger than the target 200-case final set so the author can
defer noise while preserving coverage. Final selection and any agreement study
belong to later work after genuine human annotation; they are not Phase 2 claims.

Candidate text is historical public TWCS content, sanitized for URLs, handles,
email-like strings, and long numeric identifiers. It is committed only because the
author must see the cases and the assignment requires delivery of the eventual
evaluation set. It must not be repurposed as training or retrieval data.
