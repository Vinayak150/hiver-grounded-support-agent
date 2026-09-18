#!/usr/bin/env python3
"""Analyze real Phase 5A DEVELOPMENT judge outputs; never synthesize missing data."""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.spotify import write_json  # noqa: E402
from support_agent.evaluation.bootstrap import percentile_bootstrap_ci  # noqa: E402
from support_agent.judge.agreement import (  # noqa: E402
    exact_agreement,
    order_bias_flip_rate,
    weighted_cohen_kappa,
    within_one_agreement,
)
from support_agent.judge.schema import SCORE_FIELDS  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Real judge artifact is required: {path}")
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def rate(values: list[bool]) -> float:
    return sum(values) / len(values)


def system_summary(records, config):
    summary = {}
    for field in SCORE_FIELDS:
        values = [int(item[field]) for item in records]
        summary[field] = {
            "mean": round(statistics.mean(values), 6),
            "median": statistics.median(values),
            "distribution": dict(sorted(Counter(values).items())),
            "mean_bootstrap_ci": percentile_bootstrap_ci(
                values,
                statistics.mean,
                samples=int(config["bootstrap_samples"]),
                seed=20260918,
                confidence_level=float(config["bootstrap_confidence_level"]),
            ),
        }
    reasons = Counter(reason for item in records for reason in item["failure_reasons"])
    return {
        "case_count": len(records),
        "dimensions": summary,
        "overall_pass_rate": round(rate([bool(item["overall_pass"]) for item in records]), 6),
        "critical_failure_rate": round(
            rate([bool(item["critical_failure"]) for item in records]), 6
        ),
        "failure_reason_distribution": dict(sorted(reasons.items())),
    }


def repeatability_report(records, manifest):
    selected = set(manifest["repeatability"]["case_ids"])
    runs: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for item in records:
        if item["system"] == "proposed" and item["case_id"] in selected:
            runs[str(item["run_id"])][str(item["case_id"])] = item
    expected = ["primary"] + [
        f"repeat-{value}" for value in range(2, int(manifest["repeatability"]["passes"]) + 1)
    ]
    if any(set(runs[name]) != selected for name in expected):
        raise ValueError("Repeatability raw runs are incomplete or misaligned.")
    pairs = list(combinations(expected, 2))
    dimension_metrics = {}
    variance_values = []
    ordered_ids = sorted(selected)
    for field in SCORE_FIELDS:
        exact, within, kappas = [], [], []
        for left, right in pairs:
            a = [int(runs[left][case_id][field]) for case_id in ordered_ids]
            b = [int(runs[right][case_id][field]) for case_id in ordered_ids]
            exact.append(exact_agreement(a, b))
            within.append(within_one_agreement(a, b))
            kappas.append(weighted_cohen_kappa(a, b))
        dimension_metrics[field] = {
            "exact_agreement": statistics.mean(exact),
            "within_one_agreement": statistics.mean(within),
            "pairwise_quadratic_weighted_kappa": statistics.mean(kappas),
        }
        variance_values.extend(
            statistics.pvariance([int(runs[name][case_id][field]) for name in expected])
            for case_id in ordered_ids
        )
    pass_agreement, critical_agreement = [], []
    for left, right in pairs:
        pass_agreement.append(
            exact_agreement(
                [bool(runs[left][case_id]["overall_pass"]) for case_id in ordered_ids],
                [bool(runs[right][case_id]["overall_pass"]) for case_id in ordered_ids],
            )
        )
        critical_agreement.append(
            exact_agreement(
                [bool(runs[left][case_id]["critical_failure"]) for case_id in ordered_ids],
                [bool(runs[right][case_id]["critical_failure"]) for case_id in ordered_ids],
            )
        )
    return {
        "label": "LLM SELF-CONSISTENCY / REPEATABILITY",
        "case_count": len(selected),
        "passes": len(expected),
        "dimensions": dimension_metrics,
        "mean_score_variance": statistics.mean(variance_values),
        "overall_pass_agreement": statistics.mean(pass_agreement),
        "critical_failure_agreement": statistics.mean(critical_agreement),
    }


def main() -> int:
    config = json.loads(Path("configs/judge.yaml").read_text(encoding="utf-8"))
    manifest = json.loads(
        Path("results/dev_judge_sample_manifest.json").read_text(encoding="utf-8")
    )
    records = read_jsonl(Path("results/dev_judge_results.jsonl"))
    primary = [item for item in records if item["run_id"] == "primary"]
    systems = defaultdict(list)
    for item in primary:
        systems[str(item["system"])].append(item)
    if set(systems) != {"fixed", "lexical", "proposed"}:
        raise ValueError("Judge output must contain all three blinded systems.")
    proposed_source = {
        item["case_id"]: item for item in read_jsonl(Path("results/dev_proposed_agent.jsonl"))
    }
    proposed_records = systems["proposed"]
    slices = {}
    slice_values = {
        "action": lambda source: str(source["action"]),
        "evidence_sufficient": lambda source: str(bool(source["evidence_sufficient"])),
        "intent": lambda source: str(source["intent"]),
        "risk": lambda source: "HAS_RISK" if source["risk_tags"] else "NO_RISK",
    }
    for slice_name, getter in slice_values.items():
        grouped = defaultdict(list)
        for record in proposed_records:
            grouped[getter(proposed_source[record["case_id"]])].append(record)
        slices[slice_name] = {
            key: system_summary(values, config) for key, values in sorted(grouped.items())
        }
    summary = {
        "phase": "5A",
        "split": "DEVELOPMENT",
        "label": "UNVALIDATED LLM-JUDGE DEVELOPMENT DIAGNOSTICS",
        "systems": {key: system_summary(values, config) for key, values in sorted(systems.items())},
        "proposed_slices": slices,
        "human_judge_agreement_status": "NOT_YET_MEASURED",
        "frozen_evaluation_touched": False,
    }
    write_json(Path("results/dev_judge_summary.json"), summary)
    write_json(Path("results/judge_repeatability.json"), repeatability_report(records, manifest))

    order_records = read_jsonl(Path("results/dev_judge_order_bias.jsonl"))
    grouped_order = defaultdict(dict)
    for item in order_records:
        grouped_order[str(item["case_id"])][str(item["order"])] = item
    if any(set(values) != {"first", "swapped"} for values in grouped_order.values()):
        raise ValueError("Order-bias results are incomplete.")
    ordered_ids = sorted(grouped_order)
    order_summary = {
        "label": "LLM POSITION / ORDER BIAS CHECK",
        "case_count": len(ordered_ids),
        "preference_flip_rate": order_bias_flip_rate(
            [str(grouped_order[value]["first"]["preference"]) for value in ordered_ids],
            [str(grouped_order[value]["swapped"]["preference"]) for value in ordered_ids],
        ),
    }
    write_json(Path("results/judge_order_bias.json"), order_summary)
    print("Wrote unvalidated DEVELOPMENT judge diagnostics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
