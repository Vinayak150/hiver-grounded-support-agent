# Phase 4 agent architecture

## Scope and data boundary

The proposed agent is deterministic and runs without an external API. The intent
classifier and historical index are fitted only on 19,793 TRAIN threads. The
2,594 DEVELOPMENT threads are used only for unlabeled distribution diagnostics
and bounded heuristic threshold calibration. Frozen evaluation text and its
separate AI provisional labels are not loaded by the Phase 4 scripts.

```text
customer message
    ↓
word/character TF-IDF intent classifier
    ↓
deterministic risk analysis
    ↓
TRAIN-only hybrid historical retrieval
    ↓
evidence sufficiency gate
    ↓
deterministic extractive composer
    ↓
grounding and safety verifier
    ↓
AUTO_HANDLE or ESCALATE
```

## Components

The classifier combines word unigrams/bigrams and character 3–5 grams in a
class-balanced logistic regression. Its targets are TRAIN-side deterministic
taxonomy groups, so confidence is model confidence against weak labels rather
than human-validated accuracy. No weak-label cross-validation result is reported.

The retriever filters private/unusable replies, caps exact reply templates at two,
and indexes 11,025 TRAIN cases. A candidate pool of 40 is reranked by word
similarity (0.32), character similarity (0.23), predicted-intent compatibility
(0.20), reply quality (0.15), conversation-context compatibility (0.10), and a
duplicate-template penalty (0.10). It returns five cases with each component
score, the historical reply, and source thread ID.

The evidence gate uses the classifier confidence and margin, top retrieval score,
customer similarity, top-five intent agreement, template concentration, and risk
signals. Its numeric thresholds are bounded DEVELOPMENT distribution quantiles;
they are not optimized for correctness and must not be interpreted as validated
safety or accuracy thresholds.

The composer extracts at most two sanitized sentences from the highest-ranked
TRAIN reply. It removes handles, URLs, email-like values, names in greetings, and
agent initials. Only substantive clarifying questions or configured procedural
troubleshooting steps can be drafted; link-dependent fragments and sentences
matching unsupported action, private inspection, payment promise, or policy
patterns are excluded. It does not paraphrase or add outside facts.

The verifier checks source references, evidence-token coverage, identifiers,
unsupported actions, private-account claims, payment promises, and policy claims.
Automation is allowed only if every upstream gate and the verifier pass. Latency
is intentionally null in committed outputs so two runs can be compared byte for
byte; the manifest records this omission explicitly.

## Outputs

`make agent-dev` writes the structured DEVELOPMENT predictions, a traceability
manifest, and aggregate diagnostics under `results/`. These are engineering
artifacts, not final evaluation results. Each structured output can be converted
to the Phase 3 `Prediction` schema without losing action, retrieval, evidence, or
safety metadata.
