# Phase 3 Baselines

## Status

Phase 3 provides two intentionally simple engineering baselines. They generated
predictions for the 2,594-thread DEVELOPMENT split only. No human gold exists, so
this document reports behavior and corpus statistics—not accuracy, safety,
retrieval relevance, or response-quality scores.

## Baseline 1: fixed intent and always escalate

`fixed-intent-always-escalate-v1` predicts `playback_or_app_behavior` for every
case, always selects `ESCALATE`, and returns one generic acknowledgement/handoff.
The intent is the largest TRAIN-side lexical signal group (6,022 of 19,793 TRAIN
threads), not a human-labelled majority class. Its purpose is to establish a
transparent floor and show that maximal escalation provides no useful automation.

It produced 2,594 DEVELOPMENT predictions. It does not retrieve evidence and does
not claim to resolve any case.

## Baseline 2: lexical historical neighbor

`train-lexical-neighbor-v1` fits only TRAIN customer text using:

- word unigram/bigram TF-IDF;
- character-within-word 3–5 gram TF-IDF;
- weighted cosine similarity;
- deterministic top-3 historical neighbors.

The source TRAIN partition contains 19,793 threads. Replies failing the public
usability proxy removed 5,705 threads, and an exact normalized reply-template cap
removed another 934. The resulting retrieval corpus contains 13,154 threads and
11,887 distinct normalized reply templates. DEVELOPMENT, GOLDEN_CANDIDATE, and the
frozen 200 IDs are rejected by automated guards.

The predicted intent is the current train-side provisional taxonomy group of the
top neighbor. This is a weak label, not human truth. When automation is allowed,
the reply is the sanitized historical Spotify reply from that TRAIN neighbor.

### Heuristic action calibration

The action threshold is `0.359356`, the configured 75th percentile of DEVELOPMENT
top-1 similarity, bounded by the predeclared `[0.30, 0.85]` range. No labels or
accuracy calculations informed it. A prediction may use `AUTO_HANDLE` only when:

1. top-1 similarity meets the threshold;
2. the retrieved reply passed the public usability proxy; and
3. the DEVELOPMENT request triggers no configured private/sensitive risk marker.

Otherwise the baseline escalates with a fixed safe handoff. This is heuristic
calibration, not validated threshold optimization.

## What is not measured

Phase 3 does not report intent accuracy, action safety, automation correctness,
retrieval relevance, response quality, confidence intervals, or frozen benchmark
performance. Those require genuine human labels and, for response metrics, human
response-quality evidence.

Regenerate the deterministic DEVELOPMENT artifacts with:

```bash
make baselines-dev
```
