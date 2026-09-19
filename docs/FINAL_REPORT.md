# Hiver Grounded Support Agent — Near-final report

**Status:** engineering-complete pre-evaluation draft.

**Final headline:** `PENDING_HUMAN_GOLD`.

**Retained candidate:** `spotify-grounded-agent-v1.0-final-candidate` (original Phase 4).
**Scope warning:** every quality number below is an unvalidated DEVELOPMENT diagnostic,
not a final benchmark result.

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
annotation, leakage audits, bootstrap metrics, cached judge diagnostics, and strict
pre-final-evaluation gates.

## 3. What I deliberately did not build

This is not a current Spotify policy engine, private account-data interface, refund or
subscription mutation service, production queue integration, or unrestricted
generative agent. TWCS contains historical public exchanges from 2008–2017; it cannot
authorize present policy, prove that an issue was resolved, or show private actions.
Those missing capabilities are not simulated. Sensitive cases escalate rather than
claiming access the system does not have.

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

The final annotation file currently has **zero** human rows. AI suggestions are stored
separately as `AI_PROVISIONAL` and are never accepted as gold. The final benchmark is
blocked until 150–250 frozen cases are explicitly finalized by a human; the benchmark
runner then evaluates all three systems with bootstrap intervals and intent/action
slices. Correct & Safe Automation Coverage additionally requires human response-quality
decisions for proposed automated replies.

## 5. Baselines and proposed system

The fixed baseline predicts the largest TRAIN-side weak intent group and always
escalates. It is deliberately safe but offers no automation. The lexical baseline
retrieves a nearest TRAIN reply and automates only above an unlabeled DEVELOPMENT
similarity threshold with no risk marker. The proposed system adds the learned weak-label
classifier, multi-signal retrieval, evidence sufficiency, risk detection, grounded
composition, and verification.

The official candidate is the **original Phase 4** behavior. Phase 4.1 was one bounded
remediation experiment; a 45-pair DEVELOPMENT comparison found negative deltas and an
increase in critical failures, so it was rejected and is not the default.

## 6. Development results

### UNVALIDATED LLM-JUDGE DEVELOPMENT DIAGNOSTICS

On the Phase 5A cohort, derived overall pass rates were:

| System | Pass rate |
| --- | ---: |
| Fixed always-escalate | 35.00% |
| Lexical neighbor | 26.25% |
| Original proposed agent | 22.50% |

These results do **not** establish that the fixed baseline is the best support system.
The 80-case cohort intentionally included all 65 proposed `AUTO_HANDLE` cases plus only
15 stratified escalations, so it is an automation stress cohort rather than a natural
prevalence sample. The judge was Groq `openai/gpt-oss-20b`; human agreement was not
measured. Repeatability was useful but imperfect, and the order-bias experiment flipped
the normalized winner in 37.5% of only eight cases.

The Phase 4.1 comparison used 45 of 60 planned complete pairs because provider quota
stopped collection. It found 7 improved, 21 unchanged, and 17 regressed cases; pass rate
fell from 44.44% to 37.78%, while critical failures increased from 3 to 5. Missingness
risk was classified MODERATE. The original candidate was retained.

## 7. Top five failure modes

All examples are sanitized or paraphrased DEVELOPMENT cases; none comes from the frozen
set.

1. **Extractive grounding/judge mismatch (33/48 audited cases).** In
   `twcs-9b5147e867230f3d1be5`, an extracted settings instruction was source-supported,
   yet the judge/audit relationship blurred entailment with whether the reply answered
   the right question. Future work should score source entailment and answer adequacy
   separately with human adjudication.
2. **Low answer coverage (27/48).** In `twcs-0ea067d0e84ece97fd0c`, a download failure
   received only a country question. Lexical evidence plausibility did not guarantee
   coverage. A human-trained semantic coverage gate or evidence synthesizer is needed.
3. **Generic or redundant clarification (21/48).** In
   `twcs-e08530195cfe5667eb3f`, the customer had already supplied device and software
   details, but the response asked for them again. Context-slot checks should penalize
   requests for already-present facts.
4. **Critical-label protocol violations (16/48).** Several records were marked critical
   without a declared critical code. Future judge records should fail schema validation
   when critical flags and codes disagree, followed by human adjudication.
5. **Generic safe-reply judge bias (10/48).** In
   `twcs-167bbfcfda1a878667ee`, a no-claim fixed handoff could pass while a specific reply
   failed, even though neither demonstrated resolution. Safety, usefulness, and
   automation value should remain separate human-reviewed outcomes.

## 8. What is misleading about my headline number?

There is no valid final headline number yet. The visible DEVELOPMENT pass rates come
from an LLM judge with no measured human agreement. The cohort oversampled proposed
automation decisions and therefore cannot estimate production prevalence. The judge
showed material order instability and sometimes rewarded generic, low-exposure replies.
Its critical labels also sometimes conflicted with the declared protocol.

Historical public replies are evidence of past wording, not proof of issue resolution,
current policy, causal effectiveness, or account action. TWCS is old and lacks private
outcomes. A conservative agent can also make automation coverage appear “safe” simply
by escalating almost everything. Conversely, raw automation can look impressive while
hiding wrong or unhelpful replies. For those reasons, neither LLM-judge pass rate nor
automation coverage is a defensible headline. The intended headline—Correct & Safe
Automation Coverage—remains pending genuine intent/action gold and human response-quality
review.

## 9. What I would do next week

1. Human-finalize at least 150 frozen intent/action annotations and document adjudication.
2. Human-rate a representative rubric sample and measure weighted kappa, Spearman,
   exact, within-one, and binary-pass agreement with the LLM judge.
3. Human-review every proposed final-set automated reply for response quality, then run
   the frozen benchmark exactly once through `make final-eval`.
4. Use only post-benchmark human error analysis—not judge scores—to design a future
   evidence-synthesis and answer-coverage revision.
5. Calibrate automation thresholds against human safety outcomes and report coverage
   together with missed-escalation risk.
6. Separate current-policy retrieval from historical-resolution retrieval before any
   production claim.
