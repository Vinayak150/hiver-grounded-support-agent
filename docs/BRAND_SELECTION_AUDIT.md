# Phase 1.5 Brand Selection Audit

## Why This Audit Was Necessary

The original Phase 1 rule selected `AmazonHelp` using a deterministic,
volume-first lexicographic priority. That result is retained as the historical
Phase 1 outcome, but raw volume should have diminishing value for this assignment.
At 10,000 reconstructed multi-turn threads, a brand already has 40–67 times the
anticipated 150–250 example evaluation set, leaving ample material for retrieval,
development splits, and error analysis. This audit therefore caps corpus credit
rather than allowing additional scale to decide the result.

## Candidates

`AmazonHelp`, `SpotifyCares`, `AppleSupport`, `XboxSupport`, `hulu_support`, and
`Uber_Support` were compared from the real TWCS profile. The first four were
also manually reviewed through deterministic stratified samples.

## Raw Evidence

All values are historical TWCS aggregates or explicitly named proxies; they are
not resolution rates or current policy claims.

| Account | Linked inbound | Multi-turn | Public containment | Generic/redirect | Duplicate reply | Top template | Parent-link quality |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AmazonHelp | 189,132 | 51,260 | 77.74% | 18.08% | 9.09% | 0.37% | 99.4012% |
| SpotifyCares | 45,180 | 10,500 | 97.38% | 2.47% | 17.78% | 1.14% | 99.8636% |
| AppleSupport | 119,895 | 28,144 | 85.61% | 14.00% | 22.39% | 8.35% | 99.8016% |
| XboxSupport | 25,842 | 8,396 | 95.43% | 4.19% | 28.20% | 5.81% | 99.0023% |
| hulu_support | 24,556 | 5,897 | 76.17% | 23.80% | 0.57% | 0.15% | 99.5428% |
| Uber_Support | 65,924 | 15,088 | 60.28% | 37.61% | 62.94% | 7.83% | 99.8632% |

## Sufficiency Threshold

The declared saturation function is `min(1, multi_turn_threads / 10,000)`.
AmazonHelp, SpotifyCares, AppleSupport, and Uber_Support are sufficient;
XboxSupport is near-sufficient (83.96%), and hulu_support is smaller (58.97%).
AmazonHelp's extra 40,760 multi-turn threads over SpotifyCares receive no
additional corpus credit. They are optional extra material, not meaningful extra
value for this bounded assignment.

## Manual Conversation Audit

The tracked audit includes 160 unique conversations: 40 per reviewed account,
with 10 deterministic samples from each of `multi_turn`,
`high_public_containment`, `generic_redirect`, and `repeated_template`. Only IDs,
labels, and terse non-sensitive notes are stored in
[`data/annotations/brand_audit.csv`](../data/annotations/brand_audit.csv); raw text
remains local-only and is not committed. This is a single-reviewer diagnostic
sample, not a golden set or resolution study.

| Account | Historical value H/M/L | Publicly actionable Y/P/N | Private lookup Y/N | Template-like Y/N | Multi-turn usefulness H/M/L |
| --- | --- | --- | --- | --- | --- |
| AmazonHelp | 6 / 9 / 25 | 11 / 7 / 22 | 28 / 12 | 21 / 19 | 9 / 19 / 12 |
| SpotifyCares | 10 / 11 / 19 | 16 / 7 / 17 | 22 / 18 | 19 / 21 | 8 / 11 / 21 |
| AppleSupport | 9 / 19 / 12 | 21 / 7 / 12 | 19 / 21 | 22 / 18 | 3 / 13 / 24 |
| XboxSupport | 9 / 11 / 20 | 15 / 5 / 20 | 24 / 16 | 20 / 20 | 6 / 10 / 24 |

The strata intentionally over-represent generic and repeated-template cases, so
their aggregated manual value is a low-weight diagnostic signal. Spotify's useful
examples more often show public device/version/network diagnosis and next steps
before any private handoff. Amazon's weak sample cases disproportionately route
account-specific matters away from the public channel. Apple shows useful public
known-issue guidance but a narrow, repeated workaround template. No case proves
the customer was resolved.

## Assignment-Fit Dimensions

Topic diversity is normalized lexical entropy over linked inbound text.
Escalation-learning is a deterministic incidence proxy for account/private,
billing/payment, security/access, and high-conflict terms. Neither is a final
intent taxonomy or gold escalation label.

| Account | Corpus | Grounding | Low generic | Anti-template | Topic diversity | Reconstruction | Escalation | Manual value |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AmazonHelp | 1.000 | 0.774 | 0.819 | 0.909 | 0.618 | 0.994 | 0.222 | 0.263 |
| SpotifyCares | 1.000 | 0.974 | 0.975 | 0.822 | 0.640 | 0.999 | 0.267 | 0.388 |
| AppleSupport | 1.000 | 0.856 | 0.860 | 0.776 | 0.609 | 0.998 | 0.428 | 0.463 |
| XboxSupport | 0.840 | 0.954 | 0.958 | 0.718 | 0.660 | 0.990 | 0.153 | 0.363 |
| hulu_support | 0.590 | 0.762 | 0.762 | 0.994 | 0.667 | 0.995 | 0.174 | 0.500* |
| Uber_Support | 1.000 | 0.603 | 0.624 | 0.371 | 0.629 | 0.999 | 0.414 | 0.500* |

`*` Hulu and Uber were not manually audited; 0.5 is a neutral placeholder, not
evidence. Spotify's substantially higher public-containment proxy (97.38% versus
Amazon's 77.74%) and lower generic/redirect proxy (2.47% versus 18.08%) materially
improve grounding density once both have enough data.

## Sensitivity Analysis

The transparent composite uses the five declared normalized weight sets in
[`configs/brand_audit.json`](../configs/brand_audit.json). Together they vary the
emphasis on corpus sufficiency, grounding, generic avoidance, template collapse,
diversity, reconstruction, escalation, and the diagnostic manual signal.

| Weight set | Amazon | Spotify | Apple | Xbox | Hulu | Uber | Winner |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Balanced | 0.7223 | 0.7936 | 0.7661 | 0.7426 | 0.7084 | 0.6228 | SpotifyCares |
| Grounding-heavy | 0.7660 | 0.8726 | 0.8057 | 0.8313 | 0.7525 | 0.5985 | SpotifyCares |
| Reproducibility/data-quality-heavy | 0.7684 | 0.8075 | 0.8056 | 0.7481 | 0.7146 | 0.7324 | SpotifyCares |
| Diversity-heavy | 0.7119 | 0.7534 | 0.7268 | 0.7099 | 0.7188 | 0.6050 | SpotifyCares |
| Conservative-safety-heavy | 0.6890 | 0.7814 | 0.7543 | 0.7352 | 0.6807 | 0.6059 | SpotifyCares |

Spotify wins all five. The reproducibility/data-quality configuration is close to
Apple (0.8075 versus 0.8056), but none of the plausible configurations flips the
winner; the decision does not depend on a narrow volume weighting.

## Final Brand Decision

**Initial Phase 1 selection: AmazonHelp.**

**Final post-audit selection: SpotifyCares.**

## Why This Brand

SpotifyCares reaches the 10,000-thread sufficiency bar, has the strongest
public-containment and low-generic signals among sufficient major candidates,
retains 99.8636% parent-link completeness, and wins every sensitivity setting.
Its reviewed conversations offer publicly useful diagnostic questions and concrete
troubleshooting before account-specific cases move private, making the historical
corpus better grounding material than AmazonHelp's additional but saturated scale.

## Why Not the Strongest Alternatives

- **AmazonHelp:** larger and less duplicated, but post-threshold scale adds no
  corpus score and its public grounding density is lower.
- **AppleSupport:** strong public technical guidance and the largest escalation
  proxy, but lower reply variety and materially higher template concentration.
- **XboxSupport:** strong public containment and topic diversity, but below
  saturation with the highest duplicate rate among audited technical brands.
- **hulu_support / Uber_Support:** Hulu lacks multi-turn depth; Uber has poor
  public containment, high generic replies, and severe template collapse.

## Main Weakness of the Selected Brand

SpotifyCares has material template collapse: 17.78% exact normalized duplicate
replies and 19/40 diagnostic samples marked template-like, often for private
account matters. Later work must deduplicate templates and escalate private or
account-specific cases instead of generating from them.

## Limitations

- TWCS is historical Twitter support data.
- Heuristics and lexical proxies are imperfect; public replies do not prove
  resolution or current policy.
- The manual audit is small, single-reviewer, stratified, and diagnostic.
- This is selection analysis only: no taxonomy, split, golden set, retriever,
  generator, escalation classifier, or model evaluation has been implemented.
