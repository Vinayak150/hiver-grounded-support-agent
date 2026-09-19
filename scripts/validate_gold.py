#!/usr/bin/env python3
"""Validate that genuine human gold can unlock the frozen final benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.spotify import write_json  # noqa: E402
from support_agent.evaluation.gold import validate_human_gold  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold", type=Path, default=Path("data/annotations/golden_annotations.csv")
    )
    parser.add_argument(
        "--candidates", type=Path, default=Path("data/annotations/final_golden_candidates.csv")
    )
    parser.add_argument(
        "--frozen-manifest",
        type=Path,
        default=Path("data/manifests/final_golden_candidate_manifest.json"),
    )
    parser.add_argument(
        "--split-manifest", type=Path, default=Path("data/manifests/split_manifest.json")
    )
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument(
        "--annotation-config", type=Path, default=Path("configs/annotation.yaml")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/gold_validation_status.json")
    )
    arguments = parser.parse_args()
    result = validate_human_gold(
        gold_path=arguments.gold,
        candidates_path=arguments.candidates,
        frozen_manifest_path=arguments.frozen_manifest,
        split_manifest_path=arguments.split_manifest,
        taxonomy_path=arguments.taxonomy,
        annotation_config_path=arguments.annotation_config,
    )
    write_json(arguments.output, result.as_dict())
    print(f"HUMAN_LABEL_COUNT={result.human_label_count}")
    print(f"REQUIRED_MINIMUM={result.required_minimum}")
    print(f"GOLD_VALIDATION_STATUS={result.status}")
    print(
        "FINAL_EVALUATION_READY="
        + ("YES" if result.final_evaluation_ready else "NO")
    )
    if result.errors:
        print("BLOCKERS=" + json.dumps(list(result.errors), ensure_ascii=False))
    return 0 if result.final_evaluation_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
