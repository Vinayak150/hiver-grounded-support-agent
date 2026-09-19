# Golden annotation provenance

## Dataset-level disclosure

`golden_annotations.csv` contains 200 final intent/action decisions entered and
finalized by the project author. During part of the manual labeling process, the
author used AI decision-support while considering some annotations.

The annotation record did not capture assistance status reliably at the individual-row
level. Therefore:

- no row is claimed to be independently or unaidedly human-labeled;
- no row is retroactively classified as assisted or unassisted;
- `annotation_source=human` means that the stored final decision was entered and
  finalized by the human reviewer, not that the decision was necessarily made without
  AI assistance; and
- the 200 rows are a single-reviewer, human-finalized benchmark, not 200 independent
  unaided human judgments or a multi-annotator consensus set.

This disclosure changes provenance interpretation only. It does not alter any label,
reason, prediction, threshold, metric, frozen-system output, response-quality judgment,
or human–LLM judge rating. The existing frozen benchmark results remain unchanged and
must be interpreted with this annotation-independence limitation.
