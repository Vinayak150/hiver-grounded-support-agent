# Hiver Grounded Support Agent — Final report

**Status:** frozen human-gold evaluation complete.

**Final headline:** proposed intent macro-F1 **0.497** on the frozen 200-case set
(bootstrap 95% CI **[0.424, 0.562]**), accompanied by **2.5% automation coverage**
and **0% correct-and-safe automation coverage**.

**Retained candidate:** `spotify-grounded-agent-v1.0-final-candidate` (original Phase 4).

## 1. Problem framing

A useful support agent is not simply an intent classifier. It must identify the need,
find relevant support precedent, distinguish public guidance from account or policy
work, draft only what evidence supports, and automate only when both evidence and
safety gates pass. Otherwise it should escalate with a clear reason.

For this project, “good” therefore means: classify a Spotify support intent; retrieve
historically relevant public `SpotifyCares` evidence; avoid treating old public replies
as current policy; produce grounded guidance; and maximize **correct and safe**
automation rather than raw automation. Private lookup, account mutation, payment,
refund, security, or weak-evidence cases must fail closed.

## 2. What I built

The deterministic pipeline is:

```text
customer → intent classifier → risk detection → historical retrieval
         → evidence sufficiency → grounded response → verifier
         → AUTO_HANDLE or ESCALATE
```

The classifier is class-balanced word/character TF-IDF logistic regression trained on
TRAIN-side weak intent groups. The hybrid retriever combines word and character
similarity, intent compatibility, reply quality, context compatibility, and a repeated
template penalty over TRAIN history. Evidence thresholds are bounded quantiles fixed
from unlabeled DEVELOPMENT distributions. A deterministic extractive composer and
verifier block private identifiers, unsupported actions, policy claims, weak coverage,
or invalid evidence references. Each output contains intent, confidence, retrieved and
used evidence IDs, action, reply, and reason codes.

Two reproducible baselines provide context: a fixed-intent always-escalate handoff and
a TRAIN-only lexical-neighbor system. The repository also contains protected splitting,
human annotation workflows, leakage audits, bootstrap metrics, blinded judge diagnostics,
and a frozen final-evaluation runner.

## 3. What I deliberately did not build

This is not a current Spotify policy engine, private account-data interface, refund or
subscription mutation service, production queue integration, or unrestricted
generative agent. TWCS contains historical public exchanges from 2008–2017; it cannot
authorize present policy, prove that an issue was resolved, or show private actions.
Those missing capabilities are not simulated. Sensitive cases escalate rather than
claiming access the system does not have.

The final benchmark was used for measurement only. It was not used to retrain the
classifier, change thresholds, revise predictions, select another system, or improve
the retained Phase 4 candidate.

## 4. Dataset and evaluation design

TWCS contains 2,811,774 rows; its committed manifest records SHA-256
`cd297fcfa1bf6f99938be242e8e578980bc6d1b96adc8691abec9a39175b03c0`.
After real-data profiling, `SpotifyCares` was chosen because 10,500 reconstructed
multi-turn threads passed the volume-saturation threshold while producing stronger
public-containment and duplication characteristics than the initial maximum-volume
choice. Extraction produced 28,277 usable Spotify threads.

Conversation threads—not tweets—are the protection unit. A chronological split holds
out later conversations: 19,793 TRAIN, 2,594 DEVELOPMENT, and 2,619 GOLDEN_CANDIDATE
threads after exact and declared near-duplicate decontamination. The final 200 cases
were frozen before agent evaluation: 160 representative and 40 deterministic challenge
cases. No frozen ID appears in TRAIN or DEVELOPMENT.

All 200 frozen cases have human-entered, finalized intent/action labels. AI
decision-support was used during part of the manual labeling process, and per-row
assistance status was not recorded. The dataset therefore is not claimed to contain
200 independent unaided human judgments. Here, `annotation_source=human` means the
human reviewer entered and finalized the stored decision; it does not prove the
decision was made without AI assistance. This dataset-level limitation is recorded in
[`golden_annotation_provenance.md`](../data/annotations/golden_annotation_provenance.md).

Every proposed final `AUTO_HANDLE` reply also has an explicit human response-quality
decision. The benchmark reports fixed, lexical, and retained proposed predictions,
bootstrap intervals, intent/action slices, and Correct-and-Safe Automation Coverage.

## 5. Frozen final benchmark results

The proposed classifier beats both baselines on this frozen set: its intent accuracy is
0.510 versus 0.375 lexical and 0.120 fixed, and its macro-F1 is 0.497 versus 0.384 and
0.024. This is an intent-classification result, not an end-to-end superiority claim.

### Intent classification — N=200

| System | Accuracy | Macro-F1 | Weighted-F1 | Macro-F1 bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| Fixed | 0.120 | 0.023810 | 0.025714 | [0.015504, 0.031474] |
| Lexical | 0.375 | 0.383998 | 0.373679 | [0.310644, 0.448291] |
| Proposed | **0.510** | **0.497453** | **0.510869** | **[0.424263, 0.561594]** |

The proposed accuracy bootstrap 95% CI is [0.439875, 0.580000]; the lexical interval
is [0.310000, 0.440125], and the fixed interval is [0.080000, 0.170000].

### Action and automation behavior — N=200

| System | Automation coverage | Escalation recall | False escalation rate | Missed escalation rate | Unsafe auto-handle rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed | 0.000 | 1.000000 | 1.000000 | 0.000000 | 0.000000* |
| Lexical | 0.165 | 0.877778 | 0.800000 | 0.122222 | 0.333333 |
| Proposed | **0.025** | 0.955556 | **0.990909** | 0.044444 | **0.800000** |

`*` The fixed system automated zero cases, so its reported unsafe-auto rate has a zero
denominator and is not evidence of useful safe automation.

The retained proposed system is strongly conservative but badly miscalibrated. It
escalated **195/200** cases while still missing **4** cases whose gold action required
escalation. Its action confusion counts are:

- false escalation: 109;
- missed escalation: 4;
- safe auto-handle: 1;
- true escalation: 86.

Only **5/200** cases were auto-handled. Just **1/5** automation decisions aligned with
the human gold `AUTO_HANDLE` action, and the separate human response-quality gate left
**Correct-and-Safe Automation Coverage at 0/200 (0%)**. Automation coverage itself was
2.5% (bootstrap 95% CI [0.5%, 5.0%]); unsafe auto-handle rate was 80% (wide bootstrap
95% CI [33.3%, 100%]).

For comparison, lexical automated 33/200 cases, with 22 safe auto-handles and 11 missed
escalations. The fixed baseline escalated all 200, including all 110 gold `AUTO_HANDLE`
cases. These trade-offs mean the proposed agent does **not** beat both baselines overall.
It improves intent classification, but its end-to-end automation policy is not ready.

## 6. Development judge diagnostics and human agreement

Phase 5A used Groq `openai/gpt-oss-20b` as a DEVELOPMENT-only diagnostic. On its
automation-stress cohort, derived pass rates were 35.00% fixed, 26.25% lexical, and
22.50% proposed. The cohort deliberately included all 65 proposed DEVELOPMENT
`AUTO_HANDLE` cases and only 15 stratified escalations, so those rates are not final
benchmark or natural-prevalence estimates. The order-bias check flipped the normalized
winner in 37.5% of only eight cases.

A separate blinded human-agreement study is now measured on **N=40** deterministic
case/system ratings. Binary overall-pass exact agreement was **0.70**:

| Human rating | LLM false | LLM true |
| --- | ---: | ---: |
| Human false | 25 | 9 |
| Human true | 3 | 3 |

Ordinal agreement was weak or limited on most dimensions:

| Dimension | Exact | Within one | Weighted kappa | Spearman |
| --- | ---: | ---: | ---: | ---: |
| Groundedness | 0.225 | 0.425 | 0.059266 | 0.108062 |
| Relevance | 0.275 | 0.475 | 0.150693 | 0.249904 |
| Helpfulness | 0.300 | 0.525 | 0.120073 | 0.054332 |
| Safety | 0.925 | 0.975 | 0.000000 | 0.000000 |
| Brand/context | 0.225 | 0.550 | -0.039326 | -0.185186 |

The 92.5% exact safety agreement is **not validated safety agreement**: weighted kappa
and Spearman are both zero, consistent with low score variance or a prevalence effect.
The other dimensions have low exact agreement and kappas near zero. The LLM judge is
therefore useful for bounded DEVELOPMENT diagnostics and failure discovery, but it is
not a substitute for human evaluation and does not establish response quality.

The rejected Phase 4.1 experiment remains a DEVELOPMENT-only result. Across 45 complete
pairs it found 7 improved, 21 unchanged, and 17 regressed cases; pass rate fell from
44.44% to 37.78%, while critical failures increased from 3 to 5. Missingness risk was
classified MODERATE, and the original candidate was retained before final evaluation.

## 7. Top five failure modes

These failure categories were documented from 48 sanitized DEVELOPMENT audit cases;
they were not mined from the frozen set and were not used for post-benchmark tuning.
The final metrics are consistent with several risks but do not prove case-level causes.

1. **Extractive grounding/judge mismatch (33/48 audited cases).** In
   `twcs-9b5147e867230f3d1be5`, an extracted settings instruction was source-supported,
   yet the judge/audit relationship blurred entailment with whether the reply answered
   the right question. The weak human–LLM groundedness agreement (exact 0.225, weighted
   kappa 0.059) confirms that automated groundedness scores should not be treated as
   human truth.
2. **Low answer coverage (27/48).** In `twcs-0ea067d0e84ece97fd0c`, a download failure
   received only a country question. Lexical evidence plausibility did not guarantee
   coverage. The final 0% Correct-and-Safe Automation Coverage reinforces that passing
   deterministic evidence gates did not yield demonstrably acceptable automation.
3. **Generic or redundant clarification (21/48).** In
   `twcs-e08530195cfe5667eb3f`, the customer had already supplied device and software
   details, but the response asked for them again. The proposed system's 2.5% automation
   coverage does not rescue the usefulness of its few automated replies.
4. **Critical-label protocol violations (16/48).** Several DEVELOPMENT judge records
   were marked critical without a declared critical code. Together with only 70%
   binary-pass agreement, this supports treating the LLM judge as diagnostic rather
   than authoritative.
5. **Generic safe-reply judge bias (10/48).** In
   `twcs-167bbfcfda1a878667ee`, a no-claim fixed handoff could pass while a specific reply
   failed, even though neither demonstrated resolution. The final fixed baseline's 100%
   false-escalation rate illustrates why low-exposure handoffs are not useful end-to-end
   success, even when they avoid missed escalations.

## 8. What is misleading about my headline number?

The proposed macro-F1 of **0.497** is an intent-classification number, not proof of safe
automation or end-to-end agent quality. Its bootstrap 95% interval is **[0.424, 0.562]**
and should accompany the estimate because the final-set **N=200 is modest**. The intent
improvement over both baselines did not translate into automation quality: automation
coverage was only **2.5%**, and **Correct-and-Safe Automation Coverage was 0%**.

The benchmark relies on human-finalized action labels and human response-quality
judgments, both of which are subjective even under a written protocol. AI
decision-support was used during part of gold labeling, individual assisted rows were
not recorded, and the 200 labels must not be represented as independent unaided human
judgments. Historical Twitter support replies may not represent current Spotify
policies, product state, or effective private account actions. The separate LLM judge
showed only **70% overall-pass agreement** with the blinded human ratings and weak
ordinal agreement on most dimensions. Its high raw safety exact agreement is tempered
by kappa=0 and Spearman=0.

Accordingly, the defensible conclusion is narrow: the proposed classifier performed
better than both baselines on frozen intent labels, while the retained action and reply
pipeline produced inadequate automation. It would be misleading to compress those two
facts into a claim that the proposed end-to-end agent “wins.”

## 9. What I would do next week

1. Do not tune on these final cases. Freeze this result as the baseline for a new,
   separately versioned development cycle.
2. Improve evidence synthesis and answer-coverage checks using new TRAIN/DEVELOPMENT
   data and independent human review, not frozen-case errors or LLM scores as truth.
3. Calibrate a future automation policy against human safety and response-quality
   outcomes on a new validation cohort, reporting coverage with missed-escalation risk.
4. Increase the blinded human-agreement sample and investigate score-prevalence effects,
   especially the misleadingly high raw safety agreement with kappa zero.
5. Separate current-policy retrieval from historical-resolution retrieval before any
   production claim.
6. Reserve a new untouched evaluation set before testing any revised system.
