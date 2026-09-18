#!/usr/bin/env python3
"""Generate separate conservative AI-provisional suggestions for frozen cases."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.provisional import propose_labels  # noqa: E402
from support_agent.annotation.schema import (  # noqa: E402
    AI_PROVISIONAL_FIELDS,
    validate_ai_provisional_label,
)
from support_agent.annotation.store import load_frozen_candidates  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates", type=Path, default=Path("data/annotations/final_golden_candidates.csv")
    )
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument("--annotation-config", type=Path, default=Path("configs/annotation.yaml"))
    parser.add_argument(
        "--freeze-config", type=Path, default=Path("configs/evaluation_freeze.yaml")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/annotations/ai_provisional_labels.csv")
    )
    arguments = parser.parse_args()
    if arguments.output.name == "golden_annotations.csv":
        raise ValueError("AI provisional labels can never be written to golden_annotations.csv.")
    cases = load_frozen_candidates(arguments.candidates)
    taxonomy = load_taxonomy(arguments.taxonomy)
    annotation_config = json.loads(arguments.annotation_config.read_text(encoding="utf-8"))
    freeze_config = json.loads(arguments.freeze_config.read_text(encoding="utf-8"))
    labels = propose_labels(
        cases,
        taxonomy,
        freeze_config["provisional"],
        tuple(annotation_config["risk_tags"]),
    )
    for label in labels:
        validate_ai_provisional_label(
            label,
            set(taxonomy.intent_ids),
            set(annotation_config["actions"]),
            set(annotation_config["risk_tags"]),
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=AI_PROVISIONAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(label.__dict__ for label in labels)
    print(f"AI provisional labels: {len(labels)}")
    print("Human gold labels created: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
