#!/usr/bin/env python3
"""Audit AI-provisional suggestions without treating them as ground truth."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.provisional import customer_only_text  # noqa: E402
from support_agent.annotation.store import (  # noqa: E402
    AnnotationStore,
    golden_set_status,
    load_ai_provisional_labels,
    load_frozen_candidates,
)
from support_agent.data.leakage import character_ngrams, jaccard, token_set  # noqa: E402
from support_agent.data.spotify import write_json  # noqa: E402


def _distribution(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _documentation(payload: dict[str, object]) -> str:
    intent_rows = "\n".join(
        f"| `{key}` | {value} |" for key, value in payload["suggested_intent_distribution"].items()
    )
    action_rows = "\n".join(
        f"| `{key}` | {value} |" for key, value in payload["suggested_action_distribution"].items()
    )
    risk_rows = "\n".join(
        f"| `{key}` | {value} |"
        for key, value in payload["suggested_risk_tag_distribution"].items()
    )
    return f"""# AI Provisional Label Audit

## Status

These statistics describe **AI_PROVISIONAL suggestions**, not human labels, gold
ground truth, agreement evidence, or final evaluation results.

- Human-confirmed frozen cases: {payload["human_gold_labels_confirmed"]}
- Golden-set status: `{payload["golden_set_status"]}`

## Suggested intent distribution

| Suggested intent | Cases |
| --- | ---: |
{intent_rows}

## Suggested action distribution

| Suggested action | Cases |
| --- | ---: |
{action_rows}

## Suggested risk-tag distribution

| Risk tag | Cases |
| --- | ---: |
{risk_rows}

## Uncertainty and consistency

- Low-confidence cases: {payload["low_confidence_count"]}
- `UNSURE` intent/action cases: {payload["unsure_count"]}
- Similar case pairs reviewed: {payload["consistency_audit"]["similar_pairs_reviewed"]}
- Inconsistent similar pairs: {payload["consistency_audit"]["inconsistent_pair_count"]}
- Risk/action contradictions: {payload["risk_action_contradiction_count"]}
- Taxonomy-boundary conflicts: {payload["taxonomy_boundary_conflict_count"]}

The review CLI never auto-accepts these suggestions. Only an explicit human
accept/correct action may create a row in `golden_annotations.csv`.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates", type=Path, default=Path("data/annotations/final_golden_candidates.csv")
    )
    parser.add_argument(
        "--labels", type=Path, default=Path("data/annotations/ai_provisional_labels.csv")
    )
    parser.add_argument("--config", type=Path, default=Path("configs/evaluation_freeze.yaml"))
    parser.add_argument("--output", type=Path, default=Path("results/provisional_label_audit.json"))
    parser.add_argument("--docs", type=Path, default=Path("docs/PROVISIONAL_LABEL_AUDIT.md"))
    parser.add_argument(
        "--human-annotations",
        type=Path,
        default=Path("data/annotations/golden_annotations.csv"),
    )
    arguments = parser.parse_args()
    cases = load_frozen_candidates(arguments.candidates)
    labels = load_ai_provisional_labels(arguments.labels)
    if set(labels) != {case.case_id for case in cases}:
        raise ValueError("Provisional labels must cover every frozen case exactly once.")
    config = json.loads(arguments.config.read_text(encoding="utf-8"))["provisional"]
    ordered_labels = [labels[case.case_id] for case in cases]
    low_confidence_ids = [
        label.case_id
        for label in ordered_labels
        if float(label.intent_confidence) < float(config["low_intent_confidence"])
        or float(label.action_confidence) < float(config["low_action_confidence"])
    ]
    unsure_ids = [
        label.case_id
        for label in ordered_labels
        if "UNSURE" in {label.suggested_intent, label.suggested_action}
    ]
    high_risk = {
        "ACCOUNT_SPECIFIC",
        "PAYMENT",
        "REFUND",
        "SECURITY",
        "PII",
        "PRIVATE_LOOKUP",
    }
    contradictions = []
    for label in ordered_labels:
        tags = {tag for tag in label.suggested_risk_tags.split("|") if tag}
        if label.suggested_action == "AUTO_HANDLE" and tags & high_risk:
            contradictions.append(
                {"case_id": label.case_id, "conflicting_tags": sorted(tags & high_risk)}
            )
    case_text = {case.case_id: customer_only_text(case) for case in cases}
    token_documents = {case_id: token_set(text) for case_id, text in case_text.items()}
    character_documents = {case_id: character_ngrams(text) for case_id, text in case_text.items()}
    similar_pairs = []
    inconsistent = []
    for left_index, left in enumerate(cases):
        for right in cases[left_index + 1 :]:
            token_score = jaccard(token_documents[left.case_id], token_documents[right.case_id])
            character_score = jaccard(
                character_documents[left.case_id], character_documents[right.case_id]
            )
            if token_score < float(
                config["similarity_audit_token_threshold"]
            ) and character_score < float(config["similarity_audit_character_threshold"]):
                continue
            pair = {
                "left_case_id": left.case_id,
                "right_case_id": right.case_id,
                "token_jaccard": round(token_score, 6),
                "character_5gram_jaccard": round(character_score, 6),
            }
            similar_pairs.append(pair)
            left_label = labels[left.case_id]
            right_label = labels[right.case_id]
            if (
                left_label.suggested_intent != right_label.suggested_intent
                or left_label.suggested_action != right_label.suggested_action
            ):
                inconsistent.append(pair)
    boundary_ids = [
        label.case_id
        for label in ordered_labels
        if "TAXONOMY_BOUNDARY" in label.uncertainty_flags.split("|")
    ]
    risk_tags = [
        tag for label in ordered_labels for tag in label.suggested_risk_tags.split("|") if tag
    ]
    human_annotations = AnnotationStore(arguments.human_annotations).load()
    human_confirmed = len({case.case_id for case in cases} & set(human_annotations))
    payload = {
        "phase": "2.6",
        "status": "AI_PROVISIONAL_NOT_GROUND_TRUTH",
        "case_count": len(cases),
        "annotation_source_distribution": _distribution(
            [label.annotation_source for label in ordered_labels]
        ),
        "suggested_intent_distribution": _distribution(
            [label.suggested_intent for label in ordered_labels]
        ),
        "suggested_action_distribution": _distribution(
            [label.suggested_action for label in ordered_labels]
        ),
        "suggested_risk_tag_distribution": _distribution(risk_tags),
        "low_confidence_count": len(low_confidence_ids),
        "low_confidence_case_ids": low_confidence_ids,
        "unsure_count": len(unsure_ids),
        "unsure_case_ids": unsure_ids,
        "consistency_audit": {
            "similar_pairs_reviewed": len(similar_pairs),
            "inconsistent_pair_count": len(inconsistent),
            "inconsistent_pairs": inconsistent,
        },
        "risk_action_contradiction_count": len(contradictions),
        "risk_action_contradictions": contradictions,
        "taxonomy_boundary_conflict_count": len(boundary_ids),
        "taxonomy_boundary_case_ids": boundary_ids,
        "human_gold_labels_confirmed": human_confirmed,
        "golden_set_status": golden_set_status(human_confirmed),
    }
    write_json(arguments.output, payload)
    arguments.docs.parent.mkdir(parents=True, exist_ok=True)
    arguments.docs.write_text(_documentation(payload), encoding="utf-8")
    print(f"Audited AI provisional labels: {len(cases)}")
    print(f"Human-confirmed frozen cases: {human_confirmed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
