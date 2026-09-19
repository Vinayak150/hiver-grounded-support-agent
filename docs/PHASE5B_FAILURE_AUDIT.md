# Phase 5B failure audit

## Scope and integrity

This is a deterministic DEVELOPMENT-only audit. The five Phase 5A historical artifacts were
read but not overwritten; their SHA-256 hashes still match commit `66ffeeb`. Frozen final
evaluation cases were not read for scoring or used for selection, and no human or AI label was
used as gold.

## Deterministic pass-rule corrections

Exactly **49** cached outputs required normalization:
`{'BRAND_CONTEXT_MINIMUM': 23, 'GROUNDEDNESS_MINIMUM': 26}`. Every correction was `true_to_false`.

| System | Raw model pass rate | Derived pass rate | Change |
|---|---:|---:|---:|
| fixed | 0.7250 | 0.3500 | -0.3750 |
| lexical | 0.3750 | 0.2625 | -0.1125 |
| proposed | 0.3125 | 0.2250 | -0.0875 |

The corrections materially changed absolute rates but not the ordering. The fixed baseline's
large correction burden shows that the model-returned boolean was unreliable; the deterministic
rule correctly enforced the predeclared rubric.

## Case audit

| Cohort | Required/observed count |
|---|---:|
| proposed_critical_failures | 15 |
| proposed_noncritical_failures | 15 |
| proposed_passes | 10 |
| fixed_pass_proposed_fail | 10 |
| order_bias_flips | 3 |
| repeatability_disagreements | 5 |

After deduplication, **48** cases were inspected with
customer context, intent, retrieval scores and excerpts, evidence/verifier state, reply, risk,
action, and every applicable judge output.

| Evidence-based classification | Cases |
|---|---:|
| AGENT_DEFECT | 5 |
| BOTH | 30 |
| CONTROL_PASS | 6 |
| INCONCLUSIVE | 4 |
| JUDGE_ARTIFACT | 3 |

The root cause is **both agent defects and judge artifacts**. Generic or already-answered
questions and top-1-only extraction are real response defects. Separately,
**15 of
16** proposed critical labels lacked any
declared critical-failure code, and exact extractive evidence was sometimes scored ungrounded.

Human agreement remains **NOT_YET_MEASURED**. Phase 5A's order-bias flip rate was 37.5% at N=8;
that cohort is too small to establish absence or magnitude of bias.

The categories overlap because one case can expose both a response defect and a judge defect.

| Ranked failure category | Count | Audited cases | Representative IDs |
|---|---:|---:|---|
| EXTRACTIVE_GROUNDING_JUDGE_CONFLICT | 33 | 68.75% | twcs-0ea067d0e84ece97fd0c, twcs-00ec4815eb9e75f6c443, twcs-b832fe5248a689d06ecf, twcs-d5a867a4d692ed77a1df, twcs-9b5147e867230f3d1be5 |
| REPLY_LOW_ANSWER_COVERAGE | 27 | 56.25% | twcs-0ea067d0e84ece97fd0c, twcs-00ec4815eb9e75f6c443, twcs-b832fe5248a689d06ecf, twcs-d5a867a4d692ed77a1df, twcs-e4dbd68f6115cabc9386 |
| REPLY_TOO_GENERIC_OR_CONTEXT_REDUNDANT | 21 | 43.75% | twcs-00ec4815eb9e75f6c443, twcs-d5a867a4d692ed77a1df, twcs-dabeec051ce653bf29bf, twcs-71c55983e5e43fbcff26, twcs-a1fbbd61bd5e25191a67 |
| CRITICAL_LABEL_PROTOCOL_VIOLATION | 16 | 33.33% | twcs-0ea067d0e84ece97fd0c, twcs-00ec4815eb9e75f6c443, twcs-b832fe5248a689d06ecf, twcs-d5a867a4d692ed77a1df, twcs-35dc5cfe4121024e3b1d |
| JUDGE_GENERIC_REPLY_BIAS | 10 | 20.83% | twcs-e08530195cfe5667eb3f, twcs-dabeec051ce653bf29bf, twcs-bc064dbd01dd8a29bdf7, twcs-167bbfcfda1a878667ee, twcs-b832fe5248a689d06ecf |
| JUDGE_REPEATABILITY_INSTABILITY | 5 | 10.42% | twcs-0ea067d0e84ece97fd0c, twcs-44ad7b86a4383c53f9bb, twcs-7d3d6219e305afb014aa, twcs-b411eb95d420693e3a95, twcs-fc466216bf9ca569b339 |
| JUDGE_POSITION_INSTABILITY | 3 | 6.25% | twcs-4a5770af112216bc021c, twcs-b501d0d8aa3b0f395645, twcs-f0e1713bf79063372fca |
| REPLY_INCOMPLETE_SURFACE_FORM | 1 | 2.08% | twcs-00e91b04f80edeb5eca9 |

## Fixed-baseline advantage

The identical fixed reply passed 28 of 80 cases, while there were
18 fixed-pass/proposed-fail cases. Its lack of factual
claims legitimately earns strong grounding and safety, but the pass rule permits a generic
handoff with relevance/helpfulness at 3 to pass. The high and inconsistent treatment of the same
generic text is therefore partly a rubric/judge artifact; the audited proposed replies also
contain genuine relevance and context-coverage defects. Conclusion: **BOTH**.

## Phase 4 generator audit

- Phase 4 used only top-1 evidence for all 65 audited
  auto-handles.
- Question-only replies: 61.
- Generic/context-redundant non-answers: 28.
- Exact extractive replies penalized as ungrounded:
  50.
- Revised auto-handles selecting top-2 evidence: 29.
- Audited auto-handles with a generic top-1 question but a concrete top-2/top-3 candidate:
  2.
- Revised full-DEVELOPMENT transitions: `{'AUTO_HANDLE->AUTO_HANDLE': 37, 'AUTO_HANDLE->ESCALATE': 28, 'ESCALATE->AUTO_HANDLE': 22, 'ESCALATE->ESCALATE': 2507}`.

## Decision and bounded remediation

**AGENT_CHANGE_JUSTIFIED.** Phase 4.1 is one frozen, versioned remediation. It searches at most
top-2 evidence, prefers complete safe action sentences, rejects URL-stripped fragments,
generic/context-redundant questions, and verifies only the evidence IDs actually used. It does
not alter the classifier, taxonomy, retrieval weights, evidence thresholds, risk rules, safety
markers, or frozen data. Original Phase 4 predictions remain byte reproducible.

## New holdout

The original holdout remains frozen at 60 DEVELOPMENT cases with zero Phase 5A or frozen-final
overlap. The final analysis cohort is the separately recorded complete-pair subset below.

## Resource-constrained paired validation

This is a **RESOURCE-CONSTRAINED DEVELOPMENT PAIRED DIAGNOSTIC** using **N=45 complete pairs**.
The planned N was 60; 15 pairs are missing solely because Groq's daily token quota ended
execution. No missing score was imputed and no partial pair was analyzed. The completed subset
has **MODERATE** missingness risk: action, evidence, risk, change-status, and retrieval strata are
broadly represented, but confidence buckets differ by up to 26.67 percentage points. This limits
generalization and does not justify statistical certainty.

### Original

| Dimension | Mean | Median | Bootstrap 95% CI for mean |
|---|---:|---:|---:|
| groundedness | 3.3556 | 3.0 | [3.0661, 3.6444] |
| relevance | 4.1111 | 4.0 | [3.8000, 4.3778] |
| helpfulness | 3.2444 | 3.0 | [2.9333, 3.5339] |
| safety | 5.0000 | 5.0 | [5.0000, 5.0000] |
| brand_context | 2.9111 | 3.0 | [2.5556, 3.2222] |

Pass: 20/45 (44.4444%), 95% CI
[31.1111%, 57.7778%].
Critical failures: 3/45
(6.6667%), 95% CI
[0.0000%, 15.5556%].

### Revised Phase 4.1

| Dimension | Mean | Median | Bootstrap 95% CI for mean |
|---|---:|---:|---:|
| groundedness | 3.0667 | 3.0 | [2.7111, 3.4000] |
| relevance | 3.5778 | 4.0 | [3.1778, 4.0000] |
| helpfulness | 2.8222 | 3.0 | [2.4667, 3.1778] |
| safety | 5.0000 | 5.0 | [5.0000, 5.0000] |
| brand_context | 2.3556 | 3.0 | [2.0222, 2.6667] |

Pass: 17/45 (37.7778%), 95% CI
[22.2222%, 51.1111%].
Critical failures: 5/45
(11.1111%), 95% CI
[2.2222%, 20.0556%].

### Paired result and decision

The predeclared outcome rule prioritizes safety regressions, then critical-failure removal, pass
transitions, and finally the five-score sum.

- Outcomes: `{'IMPROVED': 7, 'UNCHANGED': 21, 'REGRESSED': 17}`
- Binary pass transitions: `{'fail_to_pass': 2, 'pass_to_fail': 5, 'both_pass': 15, 'both_fail': 23}`
- Critical-failure transitions: `{'critical_to_noncritical': 0, 'noncritical_to_critical': 2, 'both_critical': 3, 'both_noncritical': 40}`

| Dimension | Mean paired delta | Direction | Bootstrap 95% CI |
|---|---:|---:|---:|
| groundedness | -0.2889 | NEGATIVE | [-0.6000, +0.0222] |
| relevance | -0.5333 | NEGATIVE | [-0.9333, -0.1556] |
| helpfulness | -0.4222 | NEGATIVE | [-0.7556, -0.0667] |
| safety | +0.0000 | ZERO | [+0.0000, +0.0000] |
| brand_context | -0.5556 | NEGATIVE | [-0.9111, -0.2661] |

Safety regression: **YES**.
Safety scores were unchanged in all 45 pairs. Critical failures increased from
3 to 5,
including 2 newly critical cases. Among the
15 revised AUTO_HANDLE cases, all
safety scores were unchanged and one new critical failure appeared.

Final engineering decision: **PHASE_4_1_REJECTED**.

This decision is DEVELOPMENT-only. Human agreement remains **NOT_YET_MEASURED**, and the Phase 5A
order-bias diagnostic showed 37.5% flips at N=8. These judge results are not human truth or proof
of frozen-final performance.
