# AI Provisional Label Audit

## Status

These statistics describe **AI_PROVISIONAL suggestions**, not human labels, gold
ground truth, agreement evidence, or final evaluation results.

- Human-confirmed frozen cases: 0
- Golden-set status: `AWAITING_HUMAN_CONFIRMATION`

## Suggested intent distribution

| Suggested intent | Cases |
| --- | ---: |
| `UNSURE` | 77 |
| `account_access_or_security` | 21 |
| `billing_or_payment` | 14 |
| `content_availability_or_metadata` | 18 |
| `device_or_connectivity` | 18 |
| `feature_request_or_product_feedback` | 13 |
| `library_playlist_or_saved_content` | 16 |
| `playback_or_app_behavior` | 5 |
| `subscription_or_plan` | 18 |

## Suggested action distribution

| Suggested action | Cases |
| --- | ---: |
| `AUTO_HANDLE` | 73 |
| `ESCALATE` | 127 |

## Suggested risk-tag distribution

| Risk tag | Cases |
| --- | ---: |
| `ACCOUNT_SPECIFIC` | 37 |
| `AMBIGUOUS` | 77 |
| `DEVICE_CONTEXT` | 31 |
| `LOW_CONTEXT` | 2 |
| `MULTI_INTENT` | 28 |
| `PAYMENT` | 28 |
| `PII` | 5 |
| `POLICY_SENSITIVE` | 5 |
| `PRIVATE_LOOKUP` | 28 |
| `REFUND` | 3 |
| `SECURITY` | 7 |

## Uncertainty and consistency

- Low-confidence cases: 77
- `UNSURE` intent/action cases: 77
- Similar case pairs reviewed: 0
- Inconsistent similar pairs: 0
- Risk/action contradictions: 0
- Taxonomy-boundary conflicts: 69

The review CLI never auto-accepts these suggestions. Only an explicit human
accept/correct action may create a row in `golden_annotations.csv`.
