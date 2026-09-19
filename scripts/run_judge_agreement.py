#!/usr/bin/env python3
"""Compare cached LLM judgments with genuine human rubric ratings."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.spotify import write_json  # noqa: E402
from support_agent.judge.agreement import (  # noqa: E402
    binary_pass_agreement,
    exact_agreement,
    spearman_correlation,
    weighted_cohen_kappa,
    within_one_agreement,
)

FIELDS = (
    "case_id",
    "system",
    "groundedness",
    "relevance",
    "helpfulness",
    "safety",
    "brand_context",
    "overall_pass",
    "annotation_source",
    "status",
)
DIMENSIONS = ("groundedness", "relevance", "helpfulness", "safety", "brand_context")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--human", type=Path, default=Path("data/annotations/human_judge_ratings.csv")
    )
    parser.add_argument(
        "--llm", type=Path, default=Path("results/dev_judge_v2_results.jsonl")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/human_judge_agreement.json")
    )
    arguments = parser.parse_args()
    if not arguments.human.exists():
        print("HUMAN_JUDGE_AGREEMENT_STATUS=NOT_YET_MEASURED")
        print(f"BLOCKER=missing genuine human rubric ratings: {arguments.human}")
        return 2
    with arguments.human.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Human judge rating schema is invalid.")
        human_rows = list(reader)
    if not human_rows:
        print("HUMAN_JUDGE_AGREEMENT_STATUS=NOT_YET_MEASURED")
        print("BLOCKER=no genuine human rubric ratings")
        return 2
    human: dict[tuple[str, str], dict[str, object]] = {}
    for row in human_rows:
        if row["annotation_source"] != "human" or row["status"] != "FINALIZED":
            raise ValueError("Agreement requires finalized explicit human ratings.")
        key = (row["case_id"], row["system"])
        if key in human:
            raise ValueError("Human judge ratings contain duplicate case/system rows.")
        scores = {name: int(row[name]) for name in DIMENSIONS}
        if any(not 1 <= value <= 5 for value in scores.values()):
            raise ValueError("Human judge scores must be integers from one through five.")
        normalized_pass = row["overall_pass"].casefold()
        if normalized_pass not in {"true", "false"}:
            raise ValueError("Human overall_pass must be true or false.")
        human[key] = {**scores, "overall_pass": normalized_pass == "true"}
    llm_rows = [
        json.loads(line)
        for line in arguments.llm.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    llm = {
        (str(row["case_id"]), str(row["system"])): row
        for row in llm_rows
        if row.get("run_id", "primary") == "primary"
    }
    common = sorted(set(human) & set(llm))
    if not common:
        raise ValueError("Human and LLM ratings have no common case/system rows.")
    dimensions = {}
    for name in DIMENSIONS:
        human_values = [int(human[key][name]) for key in common]
        llm_values = [int(llm[key][name]) for key in common]
        dimensions[name] = {
            "weighted_cohen_kappa": weighted_cohen_kappa(human_values, llm_values),
            "spearman": spearman_correlation(human_values, llm_values),
            "exact_agreement": exact_agreement(human_values, llm_values),
            "within_one_agreement": within_one_agreement(human_values, llm_values),
        }
    result = {
        "status": "MEASURED",
        "matched_rating_count": len(common),
        "dimensions": dimensions,
        "binary_pass_agreement": binary_pass_agreement(
            [bool(human[key]["overall_pass"]) for key in common],
            [bool(llm[key]["overall_pass"]) for key in common],
        ),
        "matched_keys": [{"case_id": case_id, "system": system} for case_id, system in common],
    }
    write_json(arguments.output, result)
    print("HUMAN_JUDGE_AGREEMENT_STATUS=MEASURED")
    print(f"MATCHED_RATINGS={len(common)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
