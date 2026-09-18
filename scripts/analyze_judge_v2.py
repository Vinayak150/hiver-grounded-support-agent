#!/usr/bin/env python3
"""Analyze complete quota-safe Phase 5A V2 DEVELOPMENT judge outputs."""

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
from support_agent.judge.schema_v2 import (  # noqa: E402
    FAILURE_CODE_MEANINGS_V2,
    SCORE_FIELDS_V2,
)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Required V2 artifact is missing: {path}")
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def bootstrap(values, config):
    return percentile_bootstrap_ci(
        [float(value) for value in values],
        statistics.mean,
        samples=int(config["bootstrap_samples"]),
        seed=20260918,
        confidence_level=float(config["bootstrap_confidence_level"]),
    )


def system_summary(records, config):
    if not records:
        raise ValueError("V2 system summary requires records.")
    dimensions = {}
    for field in SCORE_FIELDS_V2:
        values = [int(item[field]) for item in records]
        dimensions[field] = {
            "mean": round(statistics.mean(values), 6),
            "median": statistics.median(values),
            "distribution": dict(sorted(Counter(values).items())),
            "mean_bootstrap_95_ci": bootstrap(values, config),
        }
    passes = [float(bool(item["overall_pass"])) for item in records]
    critical = [float(bool(item["critical_failure"])) for item in records]
    return {
        "case_count": len(records),
        "dimensions": dimensions,
        "overall_pass_rate": round(statistics.mean(passes), 6),
        "overall_pass_rate_bootstrap_95_ci": bootstrap(passes, config),
        "critical_failure_rate": round(statistics.mean(critical), 6),
        "critical_failure_rate_bootstrap_95_ci": bootstrap(critical, config),
        "failure_code_distribution": dict(
            sorted(Counter(code for item in records for code in item["failure_codes"]).items())
        ),
    }


def repeatability_report(records, manifest):
    selected = set(manifest["repeatability"]["case_ids"])
    runs: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for item in records:
        if item["system"] == "proposed" and item["case_id"] in selected:
            runs[str(item["run_id"])][str(item["case_id"])] = item
    names = ["primary", "repeat-2", "repeat-3"]
    if any(set(runs[name]) != selected for name in names):
        raise ValueError("V2 repeatability runs are incomplete or misaligned.")
    ordered = sorted(selected)
    pairs = list(combinations(names, 2))
    dimensions = {}
    for field in SCORE_FIELDS_V2:
        exact, within, kappas = [], [], []
        for left, right in pairs:
            a = [int(runs[left][case_id][field]) for case_id in ordered]
            b = [int(runs[right][case_id][field]) for case_id in ordered]
            exact.append(exact_agreement(a, b))
            within.append(within_one_agreement(a, b))
            kappas.append(weighted_cohen_kappa(a, b))
        dimensions[field] = {
            "exact_agreement": statistics.mean(exact),
            "within_one_agreement": statistics.mean(within),
            "quadratic_weighted_kappa": statistics.mean(kappas),
        }
    pass_agreement, critical_agreement = [], []
    for left, right in pairs:
        pass_agreement.append(
            exact_agreement(
                [bool(runs[left][case_id]["overall_pass"]) for case_id in ordered],
                [bool(runs[right][case_id]["overall_pass"]) for case_id in ordered],
            )
        )
        critical_agreement.append(
            exact_agreement(
                [bool(runs[left][case_id]["critical_failure"]) for case_id in ordered],
                [bool(runs[right][case_id]["critical_failure"]) for case_id in ordered],
            )
        )
    return {
        "label": "LLM SELF-CONSISTENCY — SMALL DIAGNOSTIC COHORT",
        "case_count": 12,
        "passes": 3,
        "dimensions": dimensions,
        "mean_dimension_exact_agreement": statistics.mean(
            value["exact_agreement"] for value in dimensions.values()
        ),
        "mean_dimension_within_one_agreement": statistics.mean(
            value["within_one_agreement"] for value in dimensions.values()
        ),
        "mean_quadratic_weighted_kappa": statistics.mean(
            value["quadratic_weighted_kappa"] for value in dimensions.values()
        ),
        "overall_pass_agreement": statistics.mean(pass_agreement),
        "critical_failure_agreement": statistics.mean(critical_agreement),
        "limitation": "N=12; small diagnostic repeatability cohort, not human agreement.",
    }


def order_report(records):
    grouped = defaultdict(dict)
    for item in records:
        grouped[str(item["case_id"])][str(item["order"])] = item
    if len(grouped) != 8 or any(set(value) != {"first", "swapped"} for value in grouped.values()):
        raise ValueError("V2 order-bias results are incomplete.")
    ids = sorted(grouped)
    first = [str(grouped[case_id]["first"]["preference"]) for case_id in ids]
    swapped = [str(grouped[case_id]["swapped"]["preference"]) for case_id in ids]
    flips = sum(
        pair not in {("A", "B"), ("B", "A"), ("TIE", "TIE")}
        for pair in zip(first, swapped, strict=True)
    )
    all_preferences = first + swapped
    non_ties = sum(value != "TIE" for value in all_preferences)
    return {
        "label": "LLM POSITION / ORDER BIAS — SMALL DIAGNOSTIC COHORT",
        "case_count": 8,
        "paired_comparisons": 8,
        "judgments": 16,
        "preference_flips": flips,
        "preference_flip_rate": order_bias_flip_rate(first, swapped),
        "first_position_preference_count": sum(value == "A" for value in all_preferences),
        "second_position_preference_count": sum(value == "B" for value in all_preferences),
        "tie_count": sum(value == "TIE" for value in all_preferences),
        "first_position_tendency_excluding_ties": (
            sum(value == "A" for value in all_preferences) / non_ties if non_ties else None
        ),
        "limitation": "N=8; limited statistical power, so absence of bias is not established.",
    }


def main() -> int:
    config = json.loads(Path("configs/judge_v2.yaml").read_text(encoding="utf-8"))
    manifest = json.loads(
        Path("results/dev_judge_v2_sample_manifest.json").read_text(encoding="utf-8")
    )
    run_manifest = json.loads(
        Path("results/dev_judge_v2_run_manifest.json").read_text(encoding="utf-8")
    )
    records = read_jsonl(Path("results/dev_judge_v2_results.jsonl"))
    primary = [item for item in records if item["run_id"] == "primary"]
    if len(primary) != 240:
        raise ValueError("V2 main results must contain exactly 240 rows.")
    systems = defaultdict(list)
    for item in primary:
        systems[str(item["system"])].append(item)
    if set(systems) != {"fixed", "lexical", "proposed"} or any(
        len(values) != 80 for values in systems.values()
    ):
        raise ValueError("V2 requires exactly 80 aligned rows per system.")
    expected_ids = {str(item["case_id"]) for item in manifest["cases"]}
    if any(
        {str(item["case_id"]) for item in values} != expected_ids
        for values in systems.values()
    ):
        raise ValueError("V2 systems do not use identical case IDs.")
    models = {str(item["judge_model"]) for item in records}
    if models != {str(config["model"])}:
        raise ValueError("V2 artifacts mix judge models.")
    proposed_source = {
        str(item["case_id"]): item
        for item in read_jsonl(Path("results/dev_proposed_agent.jsonl"))
    }
    automatic = [
        item
        for item in systems["proposed"]
        if proposed_source[str(item["case_id"])]["action"] == "AUTO_HANDLE"
    ]
    if len(automatic) != 65:
        raise ValueError("V2 AUTO_HANDLE diagnostics require all 65 cases.")
    automatic_summary = system_summary(automatic, config)
    automatic_summary.update(
        {
            "critical_failure_count": sum(bool(item["critical_failure"]) for item in automatic),
            "grounding_failure_count": sum(
                int(item["groundedness"]) < 4 or "G" in item["failure_codes"]
                for item in automatic
            ),
            "safety_failure_count": sum(
                int(item["safety"]) < 4
                or any(
                    code
                    in {
                        "A",
                        "P",
                        "C",
                        "I",
                        "L",
                        "D",
                    }
                    for code in item["failure_codes"]
                )
                for item in automatic
            ),
        }
    )
    limitations = [
        "Protocol V1 used GPT-OSS-120B but did not complete because of Groq quota.",
        "V1 partial outputs are excluded from the reported comparison.",
        "Protocol V2 was declared before inspecting or finalizing V1 scores.",
        "V2 uses GPT-OSS-20B consistently for all systems.",
        "The resource-constrained 80-case sample includes every proposed AUTO_HANDLE case.",
        "Human agreement remains unmeasured.",
    ]
    summary = {
        "phase": "5A",
        "protocol": config["version"],
        "split": "DEVELOPMENT",
        "label": "UNVALIDATED LLM-JUDGE DEVELOPMENT DIAGNOSTICS",
        "provider": run_manifest["provider"],
        "model": run_manifest["model"],
        "rubric_version": run_manifest["rubric_version"],
        "prompt_version": run_manifest["prompt_version"],
        "phase5a_v1_status": config["phase5a_v1_status"],
        "phase5a_v2_reason": config["phase5a_v2_reason"],
        "v1_partial_results_used": False,
        "sample": {"total": 80, "auto_handle": 65, "escalate": 15},
        "systems": {key: system_summary(value, config) for key, value in sorted(systems.items())},
        "proposed_auto_handle_diagnostics": automatic_summary,
        "failure_code_legend": FAILURE_CODE_MEANINGS_V2,
        "overall_pass_source": run_manifest["overall_pass_source"],
        "provider_calls": run_manifest["provider_calls"],
        "cumulative_judge_accounting": run_manifest["cumulative_judge_accounting"],
        "scientific_limitations": limitations,
        "human_judge_agreement_status": "NOT_YET_MEASURED",
        "frozen_evaluation_touched": False,
        "human_gold_used": 0,
        "ai_provisional_used_as_gold": False,
    }
    write_json(Path("results/dev_judge_v2_summary.json"), summary)
    write_json(Path("results/judge_v2_repeatability.json"), repeatability_report(records, manifest))
    order_rows = read_jsonl(Path("results/dev_judge_v2_order_bias.jsonl"))
    write_json(Path("results/judge_v2_order_bias.json"), order_report(order_rows))
    print("Wrote complete unvalidated Phase 5A V2 DEVELOPMENT diagnostics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
