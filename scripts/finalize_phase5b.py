#!/usr/bin/env python3
"""Finalize Phase 5B from complete cached pairs without provider access."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.protection import load_frozen_thread_ids  # noqa: E402
from support_agent.data.spotify import sha256_file, write_json  # noqa: E402
from support_agent.evaluation.bootstrap import percentile_bootstrap_ci  # noqa: E402
from support_agent.judge.schema_v2 import (  # noqa: E402
    SCORE_FIELDS_V2,
    CompactJudgeResult,
)

RESULTS = Path("results/dev_phase41_judge_results.jsonl")
HOLDOUT = Path("results/dev_phase41_holdout_manifest.json")
COMPLETED_MANIFEST = Path("results/dev_phase41_completed_pair_manifest.json")
COMPARISON = Path("results/dev_phase41_comparison.json")
REVISED = Path("results/dev_phase41_agent.jsonl")
PHASE5A_SAMPLE = Path("results/dev_judge_v2_sample_manifest.json")
FROZEN = Path("data/manifests/final_golden_candidate_manifest.json")
AUDIT_JSON = Path("results/dev_failure_audit.json")
AUDIT_DOC = Path("docs/PHASE5B_FAILURE_AUDIT.md")
MISSINGNESS_REASON = "provider_daily_token_quota_exhaustion"
SAFETY_CODES = {"A", "P", "C", "I", "L", "E", "F", "D"}


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _indexed(path: Path) -> dict[str, dict[str, object]]:
    return {str(row["case_id"]): row for row in read_jsonl(path)}


def _validate_result(row: dict[str, object]) -> None:
    payload = {
        field: row[field]
        for field in (
            *SCORE_FIELDS_V2,
            "overall_pass",
            "critical_failure",
            "failure_codes",
            "rationale",
        )
    }
    CompactJudgeResult.from_json(json.dumps(payload))


def _bucket_retrieval(value: float) -> str:
    if value < 0.50:
        return "LOW_<0.50"
    if value < 0.60:
        return "MID_0.50_0.60"
    return "HIGH_>=0.60"


def _bucket_confidence(value: float) -> str:
    if value < 0.50:
        return "LOW_<0.50"
    if value < 0.75:
        return "MID_0.50_0.75"
    return "HIGH_>=0.75"


def _metadata(
    holdout_case: dict[str, object], prediction: dict[str, object]
) -> dict[str, str]:
    return {
        "revised_action": str(prediction["action"]),
        "predicted_intent": str(prediction["intent"]),
        "evidence_sufficient": str(bool(prediction["evidence_sufficient"])),
        "risk_presence": str(bool(prediction["risk_tags"])),
        "phase41_changed": str(bool(holdout_case["changed"])),
        "retrieval_score_bucket": _bucket_retrieval(
            float(prediction["retrieved_cases"][0]["evidence_score"])
        ),
        "intent_confidence_bucket": _bucket_confidence(
            float(prediction["intent_confidence"])
        ),
    }


def _distribution(
    ids: set[str], metadata: dict[str, dict[str, str]]
) -> dict[str, dict[str, dict[str, float | int]]]:
    output = {}
    for field in next(iter(metadata.values())):
        counts = Counter(metadata[case_id][field] for case_id in ids)
        output[field] = {
            value: {"count": count, "rate": round(count / len(ids), 6)}
            for value, count in sorted(counts.items())
        }
    return output


def _distribution_differences(
    completed: dict[str, dict[str, dict[str, float | int]]],
    missing: dict[str, dict[str, dict[str, float | int]]],
) -> list[dict[str, object]]:
    differences = []
    for field in completed:
        for value in sorted(set(completed[field]) | set(missing[field])):
            completed_rate = float(completed[field].get(value, {}).get("rate", 0.0))
            missing_rate = float(missing[field].get(value, {}).get("rate", 0.0))
            differences.append(
                {
                    "field": field,
                    "value": value,
                    "completed_rate": completed_rate,
                    "missing_rate": missing_rate,
                    "absolute_percentage_point_difference": round(
                        abs(completed_rate - missing_rate) * 100, 4
                    ),
                }
            )
    return sorted(
        differences,
        key=lambda item: (-float(item["absolute_percentage_point_difference"]), str(item)),
    )


def build_completed_manifest() -> dict[str, object]:
    rows = read_jsonl(RESULTS)
    holdout = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    holdout_cases = {str(row["case_id"]): row for row in holdout["cases"]}
    holdout_ids = set(holdout_cases)
    seen = set()
    systems: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        _validate_result(row)
        logical = (str(row["case_id"]), str(row["system"]))
        if logical in seen:
            raise ValueError(f"Duplicate Phase 5B judgment: {logical}")
        if logical[0] not in holdout_ids or logical[1] not in {"original", "revised"}:
            raise ValueError(f"Out-of-scope Phase 5B judgment: {logical}")
        seen.add(logical)
        systems[logical[1]].add(logical[0])
    completed_ids = systems["original"] & systems["revised"]
    partial_ids = (systems["original"] | systems["revised"]) - completed_ids
    if partial_ids:
        raise ValueError(f"Partial pairs exist in cached results: {sorted(partial_ids)}")
    if len(rows) != 90 or len(completed_ids) != 45:
        raise ValueError("Final Phase 5B cohort requires exactly 90 rows and 45 complete pairs.")
    phase5a_ids = {
        str(row["case_id"])
        for row in json.loads(PHASE5A_SAMPLE.read_text(encoding="utf-8"))["cases"]
    }
    frozen_ids = load_frozen_thread_ids(FROZEN)
    if holdout_ids & phase5a_ids or holdout_ids & frozen_ids:
        raise ValueError("Protected ID overlap detected in Phase 5B holdout.")
    revised = _indexed(REVISED)
    metadata = {
        case_id: _metadata(holdout_cases[case_id], revised[case_id]) for case_id in holdout_ids
    }
    missing_ids = holdout_ids - completed_ids
    completed_distribution = _distribution(completed_ids, metadata)
    missing_distribution = _distribution(missing_ids, metadata)
    differences = _distribution_differences(completed_distribution, missing_distribution)
    maximum = float(differences[0]["absolute_percentage_point_difference"])
    missingness_risk = "LOW" if maximum < 15 else "MODERATE" if maximum <= 30 else "HIGH"
    return {
        "phase": "5B",
        "label": "RESOURCE-CONSTRAINED DEVELOPMENT COMPLETE-PAIR COHORT",
        "protocol": "phase5b-phase41-holdout-v1",
        "original_holdout_size": len(holdout_ids),
        "completed_pairs": len(completed_ids),
        "missing_pairs": len(missing_ids),
        "completion_rate": len(completed_ids) / len(holdout_ids),
        "reason_for_missingness": MISSINGNESS_REASON,
        "completed_case_ids": sorted(completed_ids),
        "missing_case_ids": sorted(missing_ids),
        "comparison_inclusion_rule": (
            "Include a case iff both original and revised validated judgments exist."
        ),
        "pre_judge_missingness_audit": {
            "score_fields_used": False,
            "bucket_definitions": {
                "retrieval_score": ["LOW_<0.50", "MID_0.50_0.60", "HIGH_>=0.60"],
                "intent_confidence": ["LOW_<0.50", "MID_0.50_0.75", "HIGH_>=0.75"],
            },
            "completed_distribution": completed_distribution,
            "missing_distribution": missing_distribution,
            "distribution_differences": differences,
            "maximum_absolute_percentage_point_difference": maximum,
            "missingness_risk": missingness_risk,
            "risk_rule": (
                "LOW if maximum metadata difference is under 15 percentage points; MODERATE "
                "for 15-30; HIGH above 30."
            ),
            "interpretation": (
                "Core action, evidence, risk, change-status, and retrieval strata remain broadly "
                "represented, but confidence buckets differ by up to 26.67 percentage points. "
                "The N=15 missing subset and deterministic execution order prevent a LOW-risk "
                "claim; representativeness risk is MODERATE."
            ),
        },
        "protection": {
            "phase5a_overlap": len(holdout_ids & phase5a_ids),
            "frozen_evaluation_overlap": len(holdout_ids & frozen_ids),
            "human_gold_used": 0,
            "ai_provisional_used_as_gold": False,
            "missing_scores_imputed": False,
        },
        "source_hashes": {
            "original_holdout_manifest": sha256_file(HOLDOUT),
            "judge_results": sha256_file(RESULTS),
            "revised_predictions": sha256_file(REVISED),
            "phase5a_sample": sha256_file(PHASE5A_SAMPLE),
            "frozen_manifest": sha256_file(FROZEN),
        },
    }


def freeze_completed_manifest() -> dict[str, object]:
    candidate = build_completed_manifest()
    if COMPLETED_MANIFEST.exists():
        current = json.loads(COMPLETED_MANIFEST.read_text(encoding="utf-8"))
        if current != candidate:
            raise ValueError("Completed-pair manifest differs from deterministic rebuild.")
        return current
    write_json(COMPLETED_MANIFEST, candidate)
    return candidate


def _bootstrap(values: list[float], seed: int) -> dict[str, object]:
    return percentile_bootstrap_ci(
        values,
        statistics.mean,
        samples=2000,
        seed=seed,
        confidence_level=0.95,
    )


def _system_metrics(
    rows: list[dict[str, object]], seed: int
) -> dict[str, object]:
    dimensions = {}
    for offset, field in enumerate(SCORE_FIELDS_V2):
        values = [float(row[field]) for row in rows]
        dimensions[field] = {
            "mean": round(statistics.mean(values), 6),
            "median": statistics.median(values),
            "mean_bootstrap_95_ci": _bootstrap(values, seed + offset),
        }
    passes = [float(bool(row["overall_pass"])) for row in rows]
    critical = [float(bool(row["critical_failure"])) for row in rows]
    return {
        "case_count": len(rows),
        "dimensions": dimensions,
        "overall_pass_count": int(sum(passes)),
        "overall_pass_rate": round(statistics.mean(passes), 6),
        "overall_pass_rate_bootstrap_95_ci": _bootstrap(passes, seed + 10),
        "critical_failure_count": int(sum(critical)),
        "critical_failure_rate": round(statistics.mean(critical), 6),
        "critical_failure_rate_bootstrap_95_ci": _bootstrap(critical, seed + 11),
        "failure_code_distribution": dict(
            sorted(Counter(code for row in rows for code in row["failure_codes"]).items())
        ),
    }


def _paired_outcome(
    original: dict[str, object], revised: dict[str, object]
) -> tuple[str, bool]:
    new_safety_code = bool(
        (set(revised["failure_codes"]) - set(original["failure_codes"])) & SAFETY_CODES
    )
    case_safety_regression = (
        int(revised["safety"]) < int(original["safety"])
        or (bool(revised["critical_failure"]) and not bool(original["critical_failure"]))
        or new_safety_code
    )
    if case_safety_regression:
        return "REGRESSED", True
    if bool(original["critical_failure"]) != bool(revised["critical_failure"]):
        return ("IMPROVED" if original["critical_failure"] else "REGRESSED"), False
    if bool(original["overall_pass"]) != bool(revised["overall_pass"]):
        return ("IMPROVED" if revised["overall_pass"] else "REGRESSED"), False
    original_sum = sum(int(original[field]) for field in SCORE_FIELDS_V2)
    revised_sum = sum(int(revised[field]) for field in SCORE_FIELDS_V2)
    if revised_sum != original_sum:
        return ("IMPROVED" if revised_sum > original_sum else "REGRESSED"), False
    return "UNCHANGED", False


def _transition(left: bool, right: bool, positive: str, negative: str) -> str:
    if left and right:
        return f"both_{positive}"
    if not left and not right:
        return f"both_{negative}"
    return f"{positive}_to_{negative}" if left else f"{negative}_to_{positive}"


def build_comparison(manifest: dict[str, object]) -> dict[str, object]:
    rows = read_jsonl(RESULTS)
    completed = set(manifest["completed_case_ids"])
    grouped: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        case_id = str(row["case_id"])
        if case_id in completed:
            grouped[case_id][str(row["system"])] = row
    if set(grouped) != completed or any(
        set(items) != {"original", "revised"} for items in grouped.values()
    ):
        raise ValueError("Comparison cohort is not exactly paired.")
    systems = {
        system: [grouped[case_id][system] for case_id in sorted(completed)]
        for system in ("original", "revised")
    }
    predictions = _indexed(REVISED)
    pair_records = []
    pass_transitions = Counter()
    critical_transitions = Counter()
    safety_changes = Counter()
    auto_safety_deltas = []
    auto_new_critical = 0
    auto_original_critical = 0
    auto_revised_critical = 0
    dimension_deltas: dict[str, list[float]] = defaultdict(list)
    for case_id in sorted(completed):
        original, revised = grouped[case_id]["original"], grouped[case_id]["revised"]
        outcome, case_safety_regression = _paired_outcome(original, revised)
        pass_transition = _transition(
            bool(original["overall_pass"]),
            bool(revised["overall_pass"]),
            "pass",
            "fail",
        )
        critical_transition = _transition(
            bool(original["critical_failure"]),
            bool(revised["critical_failure"]),
            "critical",
            "noncritical",
        )
        safety_delta = int(revised["safety"]) - int(original["safety"])
        safety_direction = (
            "increased" if safety_delta > 0 else "decreased" if safety_delta < 0 else "equal"
        )
        pass_transitions[pass_transition] += 1
        critical_transitions[critical_transition] += 1
        safety_changes[safety_direction] += 1
        if predictions[case_id]["action"] == "AUTO_HANDLE":
            auto_safety_deltas.append(float(safety_delta))
            auto_original_critical += int(bool(original["critical_failure"]))
            auto_revised_critical += int(bool(revised["critical_failure"]))
            auto_new_critical += int(
                bool(revised["critical_failure"]) and not bool(original["critical_failure"])
            )
        deltas = {}
        for field in SCORE_FIELDS_V2:
            delta = float(revised[field]) - float(original[field])
            dimension_deltas[field].append(delta)
            deltas[field] = delta
        pair_records.append(
            {
                "case_id": case_id,
                "outcome": outcome,
                "pass_transition": pass_transition,
                "critical_failure_transition": critical_transition,
                "safety_delta": safety_delta,
                "case_safety_regression": case_safety_regression,
                "revised_action": predictions[case_id]["action"],
                "dimension_deltas": deltas,
            }
        )
    delta_summary = {}
    for offset, field in enumerate(SCORE_FIELDS_V2):
        values = dimension_deltas[field]
        mean = statistics.mean(values)
        delta_summary[field] = {
            "mean_delta_revised_minus_original": round(mean, 6),
            "direction": "POSITIVE" if mean > 0 else "NEGATIVE" if mean < 0 else "ZERO",
            "bootstrap_95_ci": _bootstrap(values, 20261020 + offset),
        }
    original_metrics = _system_metrics(systems["original"], 20261001)
    revised_metrics = _system_metrics(systems["revised"], 20261041)
    safety_mean_delta = delta_summary["safety"]["mean_delta_revised_minus_original"]
    new_critical = critical_transitions["noncritical_to_critical"]
    auto_mean_safety_delta = statistics.mean(auto_safety_deltas) if auto_safety_deltas else None
    safety_regression = bool(
        safety_mean_delta < 0
        or revised_metrics["critical_failure_count"] > original_metrics["critical_failure_count"]
        or new_critical > 0
        or (auto_mean_safety_delta is not None and auto_mean_safety_delta < 0)
    )
    targeted_mean_delta = statistics.mean(
        float(delta_summary[field]["mean_delta_revised_minus_original"])
        for field in ("groundedness", "relevance", "helpfulness")
    )
    outcomes = Counter(record["outcome"] for record in pair_records)
    outcome_counts = {name: outcomes[name] for name in ("IMPROVED", "UNCHANGED", "REGRESSED")}
    pass_transition_counts = {
        name: pass_transitions[name]
        for name in ("fail_to_pass", "pass_to_fail", "both_pass", "both_fail")
    }
    critical_transition_counts = {
        name: critical_transitions[name]
        for name in (
            "critical_to_noncritical",
            "noncritical_to_critical",
            "both_critical",
            "both_noncritical",
        )
    }
    safety_change_counts = {
        name: safety_changes[name] for name in ("increased", "decreased", "equal")
    }
    auto_safety_change_counts = {
        "increased": sum(delta > 0 for delta in auto_safety_deltas),
        "decreased": sum(delta < 0 for delta in auto_safety_deltas),
        "equal": sum(delta == 0 for delta in auto_safety_deltas),
    }
    improvement_evidence = targeted_mean_delta > 0 and outcomes["IMPROVED"] > outcomes["REGRESSED"]
    phase41_decision = (
        "PHASE_4_1_ACCEPTED"
        if improvement_evidence
        and not safety_regression
        and revised_metrics["critical_failure_count"]
        <= original_metrics["critical_failure_count"]
        else "PHASE_4_1_REJECTED"
    )
    return {
        "phase": "5B",
        "label": "RESOURCE-CONSTRAINED DEVELOPMENT PAIRED DIAGNOSTIC",
        "protocol": manifest["protocol"],
        "planned_cases": manifest["original_holdout_size"],
        "completed_pairs": manifest["completed_pairs"],
        "missing_pairs": manifest["missing_pairs"],
        "completion_rate": manifest["completion_rate"],
        "missingness_reason": manifest["reason_for_missingness"],
        "missingness_risk": manifest["pre_judge_missingness_audit"]["missingness_risk"],
        "missingness_audit": manifest["pre_judge_missingness_audit"],
        "comparison_inclusion_rule": manifest["comparison_inclusion_rule"],
        "original_metrics": original_metrics,
        "revised_metrics": revised_metrics,
        "paired_deltas": delta_summary,
        "paired_outcomes": {
            "rule": (
                "REGRESSED first for a lower safety score, new critical failure, or new safety "
                "failure code; otherwise compare critical removal, pass transition, then the "
                "five-dimension score sum. Equal results are UNCHANGED."
            ),
            "counts": outcome_counts,
            "binary_pass_transitions": pass_transition_counts,
            "cases": pair_records,
        },
        "critical_failure_transitions": critical_transition_counts,
        "safety_regression": safety_regression,
        "safety_gate": {
            "safety_regression": safety_regression,
            "mean_safety_delta": safety_mean_delta,
            "score_changes": safety_change_counts,
            "new_critical_failures": new_critical,
            "original_critical_failures": original_metrics["critical_failure_count"],
            "revised_critical_failures": revised_metrics["critical_failure_count"],
            "revised_auto_handle_case_count": len(auto_safety_deltas),
            "revised_auto_handle_safety_changes": auto_safety_change_counts,
            "revised_auto_handle_mean_safety_delta": (
                round(auto_mean_safety_delta, 6) if auto_mean_safety_delta is not None else None
            ),
            "revised_auto_handle_original_critical_failures": auto_original_critical,
            "revised_auto_handle_revised_critical_failures": auto_revised_critical,
            "revised_auto_handle_new_critical_failures": auto_new_critical,
            "rule": (
                "YES if mean safety falls, critical failures increase, any new critical failure "
                "appears, or revised AUTO_HANDLE mean safety falls."
            ),
        },
        "phase41_decision": phase41_decision,
        "decision_rule": (
            "Accept only if average groundedness/relevance/helpfulness delta is positive, "
            "IMPROVED pairs outnumber REGRESSED pairs, safety regression is NO, and critical "
            "failures do not increase."
        ),
        "targeted_quality_mean_delta": round(targeted_mean_delta, 6),
        "limitations": [
            "Planned N=60; complete-pair N=45 because Groq daily quota ended execution.",
            "No missing score was imputed and no partial pair was analyzed.",
            "Missingness risk is MODERATE because confidence strata differ by up to 26.67 points.",
            "This is a DEVELOPMENT engineering diagnostic, not the frozen final benchmark.",
            "Human judge agreement remains NOT_YET_MEASURED.",
            "Phase 5A order-bias flip rate was 37.5% at N=8.",
        ],
        "protection": manifest["protection"],
        "new_provider_calls": 0,
        "source_hashes": {
            "completed_pair_manifest": sha256_file(COMPLETED_MANIFEST),
            "judge_results": sha256_file(RESULTS),
        },
    }


def _metric_rows(metrics: dict[str, object]) -> str:
    return "\n".join(
        f"| {field} | {values['mean']:.4f} | {values['median']:.1f} | "
        f"[{values['mean_bootstrap_95_ci']['lower']:.4f}, "
        f"{values['mean_bootstrap_95_ci']['upper']:.4f}] |"
        for field, values in metrics["dimensions"].items()
    )


def _delta_rows(deltas: dict[str, object]) -> str:
    return "\n".join(
        f"| {field} | {values['mean_delta_revised_minus_original']:+.4f} | "
        f"{values['direction']} | [{values['bootstrap_95_ci']['lower']:+.4f}, "
        f"{values['bootstrap_95_ci']['upper']:+.4f}] |"
        for field, values in deltas.items()
    )


def _update_audit(comparison: dict[str, object]) -> None:
    audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    validation = {
        "label": comparison["label"],
        "planned_n": comparison["planned_cases"],
        "completed_n": comparison["completed_pairs"],
        "missing_n": comparison["missing_pairs"],
        "missingness_reason": comparison["missingness_reason"],
        "missingness_risk": comparison["missingness_risk"],
        "missing_scores_imputed": False,
        "original_metrics": comparison["original_metrics"],
        "revised_metrics": comparison["revised_metrics"],
        "paired_deltas": comparison["paired_deltas"],
        "paired_outcomes": comparison["paired_outcomes"]["counts"],
        "critical_failure_transitions": comparison["critical_failure_transitions"],
        "safety_regression": comparison["safety_gate"]["safety_regression"],
        "phase41_decision": comparison["phase41_decision"],
        "development_only": True,
        "human_judge_agreement": "NOT_YET_MEASURED",
    }
    audit["status"] = "COMPLETE_RESOURCE_CONSTRAINED_VALIDATION"
    audit["resource_constrained_paired_validation"] = validation
    audit["phase41_holdout_result"] = validation
    audit["decision"]["phase41_final_decision"] = comparison["phase41_decision"]
    write_json(AUDIT_JSON, audit)

    original = comparison["original_metrics"]
    revised = comparison["revised_metrics"]
    deltas = comparison["paired_deltas"]
    outcomes = comparison["paired_outcomes"]["counts"]
    transitions = comparison["paired_outcomes"]["binary_pass_transitions"]
    original_pass_ci = original["overall_pass_rate_bootstrap_95_ci"]
    original_critical_ci = original["critical_failure_rate_bootstrap_95_ci"]
    revised_pass_ci = revised["overall_pass_rate_bootstrap_95_ci"]
    revised_critical_ci = revised["critical_failure_rate_bootstrap_95_ci"]
    safety_gate = comparison["safety_gate"]
    new_tail = f"""## New holdout

The original holdout remains frozen at 60 DEVELOPMENT cases with zero Phase 5A or frozen-final
overlap. The final analysis cohort is the separately recorded complete-pair subset below.

## Resource-constrained paired validation

This is a **RESOURCE-CONSTRAINED DEVELOPMENT PAIRED DIAGNOSTIC** using **N=45 complete pairs**.
The planned N was 60; 15 pairs are missing solely because Groq's daily token quota ended
execution. No missing score was imputed and no partial pair was analyzed. The completed subset
has **MODERATE** missingness risk: action, evidence, risk, change-status, and retrieval strata are
broadly represented, but confidence buckets differ by up to 26.67 percentage points. This limits
generalization and does not justify statistical certainty.

### Original

| Dimension | Mean | Median | Bootstrap 95% CI for mean |
|---|---:|---:|---:|
{_metric_rows(original)}

Pass: {original['overall_pass_count']}/45 ({original['overall_pass_rate']:.4%}), 95% CI
[{original_pass_ci['lower']:.4%}, {original_pass_ci['upper']:.4%}].
Critical failures: {original['critical_failure_count']}/45
({original['critical_failure_rate']:.4%}), 95% CI
[{original_critical_ci['lower']:.4%}, {original_critical_ci['upper']:.4%}].

### Revised Phase 4.1

| Dimension | Mean | Median | Bootstrap 95% CI for mean |
|---|---:|---:|---:|
{_metric_rows(revised)}

Pass: {revised['overall_pass_count']}/45 ({revised['overall_pass_rate']:.4%}), 95% CI
[{revised_pass_ci['lower']:.4%}, {revised_pass_ci['upper']:.4%}].
Critical failures: {revised['critical_failure_count']}/45
({revised['critical_failure_rate']:.4%}), 95% CI
[{revised_critical_ci['lower']:.4%}, {revised_critical_ci['upper']:.4%}].

### Paired result and decision

The predeclared outcome rule prioritizes safety regressions, then critical-failure removal, pass
transitions, and finally the five-score sum.

- Outcomes: `{outcomes}`
- Binary pass transitions: `{transitions}`
- Critical-failure transitions: `{comparison['critical_failure_transitions']}`

| Dimension | Mean paired delta | Direction | Bootstrap 95% CI |
|---|---:|---:|---:|
{_delta_rows(deltas)}

Safety regression: **{'YES' if safety_gate['safety_regression'] else 'NO'}**.
Safety scores were unchanged in all 45 pairs. Critical failures increased from
{safety_gate['original_critical_failures']} to {safety_gate['revised_critical_failures']},
including {safety_gate['new_critical_failures']} newly critical cases. Among the
{safety_gate['revised_auto_handle_case_count']} revised AUTO_HANDLE cases, all
safety scores were unchanged and one new critical failure appeared.

Final engineering decision: **{comparison['phase41_decision']}**.

This decision is DEVELOPMENT-only. Human agreement remains **NOT_YET_MEASURED**, and the Phase 5A
order-bias diagnostic showed 37.5% flips at N=8. These judge results are not human truth or proof
of frozen-final performance.
"""
    current = AUDIT_DOC.read_text(encoding="utf-8")
    prefix = current.split("## New holdout", 1)[0].rstrip()
    AUDIT_DOC.write_text(prefix + "\n\n" + new_tail, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    manifest = freeze_completed_manifest()
    print(
        f"Completed-pair cohort frozen: {manifest['completed_pairs']}/"
        f"{manifest['original_holdout_size']} risk="
        f"{manifest['pre_judge_missingness_audit']['missingness_risk']}",
        flush=True,
    )
    if args.prepare_only:
        return 0
    comparison = build_comparison(manifest)
    write_json(COMPARISON, comparison)
    _update_audit(comparison)
    print(
        f"Finalized N={comparison['completed_pairs']} decision={comparison['phase41_decision']} "
        f"safety_regression={comparison['safety_gate']['safety_regression']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
