#!/usr/bin/env python3
"""Freeze and run the one-pass Phase 4.1 paired DEVELOPMENT holdout."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.queue import sanitize_public_text  # noqa: E402
from support_agent.data.protection import (  # noqa: E402
    assert_no_frozen_thread_ids,
    load_frozen_thread_ids,
)
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.evaluation.bootstrap import percentile_bootstrap_ci  # noqa: E402
from support_agent.judge.cache import JudgeCache  # noqa: E402
from support_agent.judge.provider import (  # noqa: E402
    CredentialUnavailable,
    provider_from_environment,
)
from support_agent.judge.runner import JudgeRunError  # noqa: E402
from support_agent.judge.runner_v2 import V2JudgeRunner  # noqa: E402
from support_agent.judge.sampling import stable_rank  # noqa: E402
from support_agent.judge.schema_v2 import SCORE_FIELDS_V2  # noqa: E402

CONFIG = Path("configs/judge_phase5b.yaml")
HOLDOUT = Path("results/dev_phase41_holdout_manifest.json")
RESULTS = Path("results/dev_phase41_judge_results.jsonl")
SUMMARY = Path("results/dev_phase41_judge_summary.json")
RUN_MANIFEST = Path("results/dev_phase41_judge_run_manifest.json")
ORIGINAL = Path("results/dev_proposed_agent.jsonl")
REVISED = Path("results/dev_phase41_agent.jsonl")
PHASE5A_SAMPLE = Path("results/dev_judge_v2_sample_manifest.json")
SPLITS = Path("data/manifests/split_manifest.json")
FROZEN = Path("data/manifests/final_golden_candidate_manifest.json")
CORPUS = Path("data/processed/spotify_threads.jsonl")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _stratum(item: dict[str, object]) -> str:
    return "|".join(
        (
            str(item["revised_action"]),
            str(item["intent"]),
            str(bool(item["evidence_sufficient"])),
            str(bool(item["risk_presence"])),
        )
    )


def stratified_select(
    candidates: list[dict[str, object]], count: int, seed: str
) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in candidates:
        groups[_stratum(item)].append(item)
    for key in groups:
        groups[key].sort(key=lambda item: stable_rank(f"{seed}:{key}", str(item["case_id"])))
    selected: list[dict[str, object]] = []
    while len(selected) < count:
        added = False
        for key in sorted(groups):
            if groups[key] and len(selected) < count:
                selected.append(groups[key].pop(0))
                added = True
        if not added:
            raise ValueError("Insufficient eligible cases for Phase 5B holdout.")
    return selected


def build_holdout(config: dict[str, object]) -> dict[str, object]:
    original = {str(row["case_id"]): row for row in read_jsonl(ORIGINAL)}
    revised = {str(row["case_id"]): row for row in read_jsonl(REVISED)}
    if set(original) != set(revised):
        raise ValueError("Original and revised DEVELOPMENT predictions do not align.")
    split = json.loads(SPLITS.read_text(encoding="utf-8"))
    development_ids = set(split["thread_ids"]["DEVELOPMENT"])
    phase5a_ids = {
        str(item["case_id"])
        for item in json.loads(PHASE5A_SAMPLE.read_text(encoding="utf-8"))["cases"]
    }
    frozen_ids = load_frozen_thread_ids(FROZEN)
    eligible = development_ids - phase5a_ids - frozen_ids
    cases = []
    for case_id in sorted(eligible):
        before, after = original[case_id], revised[case_id]
        changed = (before["action"], before["reply"]) != (after["action"], after["reply"])
        cases.append(
            {
                "case_id": case_id,
                "changed": changed,
                "original_action": before["action"],
                "revised_action": after["action"],
                "intent": after["intent"],
                "evidence_sufficient": after["evidence_sufficient"],
                "risk_presence": bool(after["risk_tags"]),
                "stratum": _stratum(
                    {
                        "revised_action": after["action"],
                        "intent": after["intent"],
                        "evidence_sufficient": after["evidence_sufficient"],
                        "risk_presence": bool(after["risk_tags"]),
                    }
                ),
                "sampling_rank": stable_rank(str(config["sample_seed"]), case_id),
            }
        )
    changed = [item for item in cases if item["changed"]]
    unchanged = [item for item in cases if not item["changed"]]
    selected = stratified_select(
        changed, int(config["changed_case_size"]), f"{config['sample_seed']}:changed"
    ) + stratified_select(
        unchanged, int(config["unchanged_case_size"]), f"{config['sample_seed']}:unchanged"
    )
    selected.sort(key=lambda item: str(item["case_id"]))
    selected_ids = {str(item["case_id"]) for item in selected}
    assert_no_frozen_thread_ids(selected_ids, FROZEN, "Phase 5B holdout")
    if selected_ids & phase5a_ids or len(selected) != int(config["holdout_size"]):
        raise ValueError("Phase 5B holdout exclusion or size invariant failed.")
    return {
        "phase": "5B",
        "status": "FROZEN_BEFORE_ANY_PHASE5B_JUDGE_SCORE",
        "split": "DEVELOPMENT",
        "protocol": config["version"],
        "sample_seed": config["sample_seed"],
        "sampling_method": (
            "Stable-hash round-robin over revised action, predicted intent, evidence "
            "sufficiency, and risk presence; all 22 eligible changed cases and 38 "
            "unchanged controls."
        ),
        "case_count": len(selected),
        "changed_case_count": sum(bool(item["changed"]) for item in selected),
        "unchanged_case_count": sum(not bool(item["changed"]) for item in selected),
        "strata": {
            "revised_action": dict(
                sorted(Counter(str(item["revised_action"]) for item in selected).items())
            ),
            "intent": dict(sorted(Counter(str(item["intent"]) for item in selected).items())),
            "evidence_sufficient": dict(
                sorted(Counter(str(bool(item["evidence_sufficient"])) for item in selected).items())
            ),
            "risk_presence": dict(
                sorted(Counter(str(bool(item["risk_presence"])) for item in selected).items())
            ),
        },
        "cases": selected,
        "paired_outcome_rule": (
            "REGRESSED for any safety regression, new critical failure, pass true-to-false, "
            "or lower five-score sum after higher-priority ties; IMPROVED for critical failure "
            "removal, pass false-to-true, or higher five-score sum; otherwise UNCHANGED."
        ),
        "maximum_judge_calls": 120,
        "protection": {
            "phase5a_80_excluded": True,
            "frozen_200_excluded": True,
            "frozen_evaluation_judged": False,
            "human_gold_used": 0,
            "ai_provisional_used_as_gold": False,
        },
        "source_hashes": {
            "original_predictions": sha256_file(ORIGINAL),
            "revised_predictions": sha256_file(REVISED),
            "phase5a_sample": sha256_file(PHASE5A_SAMPLE),
            "split_manifest": sha256_file(SPLITS),
            "frozen_manifest": sha256_file(FROZEN),
            "judge_config": sha256_file(CONFIG),
        },
    }


def freeze_holdout(config: dict[str, object]) -> dict[str, object]:
    candidate = build_holdout(config)
    if HOLDOUT.exists():
        existing = json.loads(HOLDOUT.read_text(encoding="utf-8"))
        if existing != candidate:
            raise ValueError("Existing Phase 5B holdout does not match deterministic rebuild.")
        return existing
    write_json(HOLDOUT, candidate)
    return candidate


def clipped(value: str, maximum: int) -> str:
    return sanitize_public_text(value)[:maximum].strip()


def evidence_for(record: dict[str, object], config: dict[str, object]) -> tuple[str, ...]:
    maximum = int(config["maximum_evidence_excerpts"])
    characters = int(config["evidence_excerpt_characters"])
    cases = list(record["retrieved_cases"])
    return tuple(clipped(str(item["historical_reply"]), characters) for item in cases[:maximum])


def _record(
    result,
    *,
    config: dict[str, object],
    provider_model: str,
    case_id: str,
    system: str,
) -> dict[str, object]:
    return {
        "protocol": config["version"],
        "provider": config["provider"],
        "judge_model": provider_model,
        "rubric_version": config["rubric_version"],
        "prompt_version": config["prompt_version"],
        "case_id": case_id,
        "system": system,
        **result.as_dict(),
    }


def run_judge(
    config: dict[str, object], manifest: dict[str, object], *, probe_only: bool
) -> int:
    try:
        provider = provider_from_environment(config)
    except CredentialUnavailable as error:
        print(f"WAITING_ON_CREDENTIALS: {error}", file=sys.stderr)
        return 2
    if provider.model != config["model"]:
        raise ValueError("Phase 5B model override is prohibited.")
    original = {str(row["case_id"]): row for row in read_jsonl(ORIGINAL)}
    revised = {str(row["case_id"]): row for row in read_jsonl(REVISED)}
    holdout_ids = [str(item["case_id"]) for item in manifest["cases"]]
    relevant_ids = set(holdout_ids)
    threads = {
        item.thread_id: item
        for item in read_threads(CORPUS)
        if item.thread_id in relevant_ids
    }
    if set(threads) != relevant_ids:
        raise ValueError("Phase 5B holdout does not reconcile with DEVELOPMENT corpus.")
    rows = read_jsonl(RESULTS)
    completed = {(str(row["case_id"]), str(row["system"])) for row in rows}
    runner = V2JudgeRunner(
        provider, JudgeCache(Path(str(config["cache_directory"]))), config
    )
    planned = []
    for case_id in holdout_ids:
        systems = ("revised", "original") if stable_rank("phase5b-order", case_id)[0] < "8" else (
            "original",
            "revised",
        )
        planned.extend((case_id, system) for system in systems)
    requests = 0
    for case_id, system in planned:
        if (case_id, system) in completed:
            continue
        source = original[case_id] if system == "original" else revised[case_id]
        try:
            result = runner.evaluate(
                case_id=case_id,
                customer=clipped(
                    threads[case_id].customer_text(), int(config["customer_context_characters"])
                ),
                reply=clipped(str(source["reply"]), int(config["reply_characters"])),
                action=str(source["action"]),
                evidence=evidence_for(source, config),
                replicate=f"phase5b-{system}",
            )
        except JudgeRunError as error:
            print(f"WAITING_ON_PROVIDER_QUOTA_OR_ERROR: {error}", file=sys.stderr)
            return 3
        rows.append(
            _record(
                result,
                config=config,
                provider_model=provider.model,
                case_id=case_id,
                system=system,
            )
        )
        write_jsonl(RESULTS, rows)
        completed.add((case_id, system))
        requests += 1
        print(
            f"Phase 5B progress validated={len(completed)}/120 "
            f"new_requests={requests} cache_hits={runner.stats.cache_hits}",
            flush=True,
        )
        if probe_only:
            print("PHASE5B_QUOTA_PROBE=AVAILABLE", flush=True)
            return 0
    if probe_only:
        print("PHASE5B_QUOTA_PROBE=ALREADY_CACHED", flush=True)
        return 0
    write_json(
        RUN_MANIFEST,
        {
            "phase": "5B",
            "protocol": config["version"],
            "provider": config["provider"],
            "model": provider.model,
            "rubric_version": config["rubric_version"],
            "prompt_version": config["prompt_version"],
            "holdout_cases": 60,
            "validated_judgments": len(rows),
            "maximum_calls": 120,
            "session_provider_stats": runner.stats.__dict__,
            "frozen_evaluation_touched": False,
            "human_gold_used": 0,
            "ai_provisional_used_as_gold": False,
            "output_hashes": {"results": sha256_file(RESULTS)},
        },
    )
    return 0


def _bootstrap(values: list[float], config: dict[str, object], seed: int) -> dict[str, object]:
    return percentile_bootstrap_ci(
        values,
        statistics.mean,
        samples=int(config["bootstrap_samples"]),
        seed=seed,
        confidence_level=float(config["bootstrap_confidence_level"]),
    )


def _system_summary(rows: list[dict[str, object]], config: dict[str, object]) -> dict[str, object]:
    dimensions = {}
    for offset, field in enumerate(SCORE_FIELDS_V2):
        values = [float(row[field]) for row in rows]
        dimensions[field] = {
            "mean": round(statistics.mean(values), 6),
            "median": statistics.median(values),
            "bootstrap_95_ci": _bootstrap(values, config, 20260919 + offset),
        }
    passes = [float(bool(row["overall_pass"])) for row in rows]
    critical = [float(bool(row["critical_failure"])) for row in rows]
    return {
        "case_count": len(rows),
        "dimensions": dimensions,
        "overall_pass_rate": round(statistics.mean(passes), 6),
        "overall_pass_rate_bootstrap_95_ci": _bootstrap(passes, config, 20260930),
        "critical_failure_rate": round(statistics.mean(critical), 6),
        "critical_failure_rate_bootstrap_95_ci": _bootstrap(critical, config, 20260931),
        "failure_code_distribution": dict(
            sorted(Counter(code for row in rows for code in row["failure_codes"]).items())
        ),
    }


def _paired_outcome(original: dict[str, object], revised: dict[str, object]) -> tuple[str, bool]:
    safety_codes = {"A", "P", "C", "I", "L", "E", "F", "D"}
    new_safety_code = bool(
        (set(revised["failure_codes"]) - set(original["failure_codes"])) & safety_codes
    )
    safety_regression = (
        int(revised["safety"]) < int(original["safety"])
        or (bool(revised["critical_failure"]) and not bool(original["critical_failure"]))
        or new_safety_code
    )
    if safety_regression:
        return "REGRESSED", True
    if bool(original["critical_failure"]) != bool(revised["critical_failure"]):
        return ("IMPROVED" if original["critical_failure"] else "REGRESSED"), False
    if bool(original["overall_pass"]) != bool(revised["overall_pass"]):
        return ("IMPROVED" if revised["overall_pass"] else "REGRESSED"), False
    old_sum = sum(int(original[field]) for field in SCORE_FIELDS_V2)
    new_sum = sum(int(revised[field]) for field in SCORE_FIELDS_V2)
    if new_sum != old_sum:
        return ("IMPROVED" if new_sum > old_sum else "REGRESSED"), False
    return "UNCHANGED", False


def analyze(config: dict[str, object], manifest: dict[str, object]) -> int:
    rows = read_jsonl(RESULTS)
    if len(rows) != 120:
        raise ValueError("Phase 5B comparison requires exactly 120 judgments.")
    grouped: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        grouped[str(row["case_id"])][str(row["system"])] = row
    expected = {str(item["case_id"]) for item in manifest["cases"]}
    if set(grouped) != expected or any(
        set(items) != {"original", "revised"} for items in grouped.values()
    ):
        raise ValueError("Phase 5B paired results are incomplete or misaligned.")
    systems = {
        name: [grouped[case_id][name] for case_id in sorted(grouped)]
        for name in ("original", "revised")
    }
    pairs = []
    for case_id in sorted(grouped):
        outcome, safety_regression = _paired_outcome(
            grouped[case_id]["original"], grouped[case_id]["revised"]
        )
        pairs.append(
            {
                "case_id": case_id,
                "outcome": outcome,
                "safety_regression": safety_regression,
                "original_pass": grouped[case_id]["original"]["overall_pass"],
                "revised_pass": grouped[case_id]["revised"]["overall_pass"],
                "original_critical": grouped[case_id]["original"]["critical_failure"],
                "revised_critical": grouped[case_id]["revised"]["critical_failure"],
            }
        )
    summary = {
        "phase": "5B",
        "label": "UNVALIDATED LLM-JUDGE DEVELOPMENT HOLDOUT DIAGNOSTIC",
        "protocol": config["version"],
        "provider": config["provider"],
        "model": config["model"],
        "rubric_version": config["rubric_version"],
        "prompt_version": config["prompt_version"],
        "holdout_cases": 60,
        "systems": {name: _system_summary(values, config) for name, values in systems.items()},
        "paired_comparison": {
            "counts": dict(sorted(Counter(item["outcome"] for item in pairs).items())),
            "safety_regression": any(item["safety_regression"] for item in pairs),
            "safety_regression_count": sum(item["safety_regression"] for item in pairs),
            "cases": pairs,
            "rule": manifest["paired_outcome_rule"],
        },
        "limitations": [
            "This is a 60-case DEVELOPMENT holdout, not the frozen final evaluation.",
            "The GPT-OSS-20B judge has no measured human agreement.",
            "Phase 5A order-bias flip rate was 37.5% at N=8.",
            "All scores remain unvalidated judge diagnostics, not ground truth.",
        ],
        "frozen_evaluation_touched": False,
        "human_gold_used": 0,
        "ai_provisional_used_as_gold": False,
    }
    write_json(SUMMARY, summary)
    print(json.dumps(summary["paired_comparison"]["counts"], sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    manifest = freeze_holdout(config)
    print(
        f"Frozen Phase 5B holdout: {manifest['case_count']} cases "
        f"({manifest['changed_case_count']} changed, "
        f"{manifest['unchanged_case_count']} unchanged).",
        flush=True,
    )
    if args.prepare_only:
        return 0
    if args.analyze_only:
        return analyze(config, manifest)
    status = run_judge(config, manifest, probe_only=args.probe_only)
    if status or args.probe_only:
        return status
    return analyze(config, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
