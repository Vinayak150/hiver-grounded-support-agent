# Evaluation Protocol

## Data roles

### TRAIN

The 19,793 TRAIN threads may fit baseline text features and provide historical
neighbors. Their taxonomy groups are deterministic weak/provisional signals, not
human intent labels. Retrieval construction filters private/unusable replies and
caps exact normalized reply templates.

### DEVELOPMENT

The 2,594 DEVELOPMENT threads support engineering validation and unsupervised
heuristic calibration. Phase 3 uses only their top-match similarity distribution
to select a threshold. It does not treat historical replies, taxonomy signals, or
any model output as ground truth.

### Frozen final evaluation

The 200 frozen cases remain untouched by prediction generation, training, tuning,
threshold selection, prompt iteration, taxonomy changes, and qualitative
optimization. Their IDs are versioned in
`data/manifests/final_golden_candidate_manifest.json` and checked by code.

### AI_PROVISIONAL

The 200 Phase 2.6 suggestions are review aids only. Phase 3 does not read them for
training, calibration, metric reporting, or artifact generation. They are not
ground truth.

### HUMAN_GOLD

There are currently zero human-confirmed gold rows. Final evaluation remains
blocked until at least 150 frozen cases receive explicit human confirmation.

## Metrics available for future evaluation

The library implements:

- intent accuracy, macro/weighted F1, per-class precision/recall/F1, and confusion
  matrices;
- escalation precision/recall/F1, false-escalation rate, missed-escalation rate,
  unsafe-auto-handle rate, and automation coverage;
- Recall@K and mean reciprocal rank when relevance labels exist;
- expected calibration error and Brier score with valid labels/probabilities;
- deterministic percentile bootstrap confidence intervals.

`CORRECT_AND_SAFE_AUTOMATION_COVERAGE` is implemented as a future metric but fails
closed unless human intent, action, and response-quality evidence are supplied.
No metric is computed merely because predictions exist.

## Frozen evaluation procedure

After genuine human labels exist, evaluation must load one frozen system artifact,
validate exact case coverage and version hashes, compute all declared metrics once,
bootstrap uncertainty with the configured seed/sample count, and preserve failures
without tuning against them. Phase 3 does not execute this procedure.
