#!/usr/bin/env python3
"""Prepare and execute the isolated quota-safe Phase 5A V2 judge protocol."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.queue import sanitize_public_text  # noqa: E402
from support_agent.baselines.lexical import first_spotify_reply  # noqa: E402
from support_agent.data.protection import assert_no_frozen_thread_ids  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.judge.cache import JudgeCache  # noqa: E402
from support_agent.judge.provider import (  # noqa: E402
    CredentialUnavailable,
    provider_from_environment,
)
from support_agent.judge.runner_v2 import V2JudgeRunner  # noqa: E402
from support_agent.judge.sampling import build_development_sample, stable_rank  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def diverse_selection(
    cases: list[dict[str, object]], count: int, seed: str, *, include_action: bool = False
) -> list[str]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in cases:
        parts = [str(item["proposed_intent"])]
        if include_action:
            parts.insert(0, str(item["proposed_action"]))
        groups["|".join(parts)].append(item)
    for key, values in groups.items():
        values.sort(key=lambda item: stable_rank(f"{seed}:{key}", str(item["case_id"])))
    selected = []
    while len(selected) < count:
        added = False
        for key in sorted(groups):
            if groups[key] and len(selected) < count:
                selected.append(str(groups[key].pop(0)["case_id"]))
                added = True
        if not added:
            raise ValueError("Insufficient cases for deterministic diverse selection.")
    return selected


def prepare_manifest(config, proposed, thread_map, development_ids, frozen_manifest, output):
    cases = build_development_sample(
        proposed,
        thread_map,
        sample_size=int(config["development_sample_size"]),
        seed=str(config["sample_seed"]),
    )
    ids = {str(item["case_id"]) for item in cases}
    if not ids <= development_ids:
        raise ValueError("V2 sample contains a non-DEVELOPMENT case.")
    assert_no_frozen_thread_ids(ids, frozen_manifest, "Phase 5A V2 judge sampling")
    automatic = [item for item in cases if item["proposed_action"] == "AUTO_HANDLE"]
    escalated = [item for item in cases if item["proposed_action"] == "ESCALATE"]
    if len(automatic) != int(config["auto_handle_sample_size"]) or len(escalated) != int(
        config["escalate_sample_size"]
    ):
        raise ValueError("V2 sample action counts do not match the predeclared protocol.")
    repeat_ids = diverse_selection(
        automatic,
        int(config["repeatability_auto_handle_size"]),
        f"{config['sample_seed']}:repeat:auto",
    ) + diverse_selection(
        escalated,
        int(config["repeatability_escalate_size"]),
        f"{config['sample_seed']}:repeat:escalate",
    )
    order_ids = diverse_selection(
        cases,
        int(config["order_bias_sample_size"]),
        f"{config['sample_seed']}:order",
        include_action=True,
    )
    estimate_ids = [
        sorted(automatic, key=lambda item: stable_rank("v2-estimate-auto", str(item["case_id"])))[
            0
        ]["case_id"],
        sorted(
            escalated,
            key=lambda item: stable_rank("v2-estimate-escalate", str(item["case_id"])),
        )[0]["case_id"],
    ]
    manifest = {
        "phase": "5A",
        "protocol": config["version"],
        "split": "DEVELOPMENT",
        "status": "PREDECLARED_BEFORE_V2_OUTPUTS",
        "phase5a_v1_status": config["phase5a_v1_status"],
        "phase5a_v2_reason": config["phase5a_v2_reason"],
        "v1_partial_results_used": False,
        "sample_seed": config["sample_seed"],
        "sampling_method": (
            "All proposed AUTO_HANDLE cases plus stable-hash round-robin strata over intent, "
            "evidence sufficiency, risk presence, and lexical challenge flags."
        ),
        "case_count": len(cases),
        "auto_handle_count": len(automatic),
        "escalate_count": len(escalated),
        "strata": {
            "intent": dict(sorted(Counter(str(x["proposed_intent"]) for x in cases).items())),
            "evidence_sufficient": dict(
                sorted(Counter(str(bool(x["evidence_sufficient"])) for x in cases).items())
            ),
            "risk_presence": dict(
                sorted(Counter(str(bool(x["has_risk_tags"])) for x in cases).items())
            ),
        },
        "cases": cases,
        "estimation_case_ids": estimate_ids,
        "repeatability": {"case_ids": sorted(repeat_ids), "passes": 3, "label": "small diagnostic"},
        "order_bias": {"case_ids": sorted(order_ids), "comparisons_per_case": 2},
        "protection": {
            "development_only": True,
            "frozen_evaluation_judged": False,
            "human_gold_used": 0,
            "ai_provisional_used_as_gold": False,
        },
        "source_hashes": {
            "proposed_predictions": sha256_file(Path("results/dev_proposed_agent.jsonl")),
            "split_manifest": sha256_file(Path("data/manifests/split_manifest.json")),
            "judge_config": sha256_file(Path("configs/judge_v2.yaml")),
        },
    }
    write_json(output, manifest)
    return manifest


def clipped(value: str, maximum: int) -> str:
    return sanitize_public_text(value)[:maximum].strip()


def evidence_for(system, record, train_map, config) -> tuple[str, ...]:
    maximum_count = int(config["maximum_evidence_excerpts"])
    maximum_chars = int(config["evidence_excerpt_characters"])
    if system == "proposed":
        candidates = list(record["retrieved_cases"])[:maximum_count]
        ids = {str(item["thread_id"]) for item in candidates}
        if not ids <= set(train_map):
            raise ValueError("V2 proposed evidence contains a non-TRAIN thread.")
        return tuple(clipped(str(item["historical_reply"]), maximum_chars) for item in candidates)
    ids = [str(value) for value in record.get("retrieved_thread_ids", [])][:maximum_count]
    if not set(ids) <= set(train_map):
        raise ValueError("V2 baseline evidence contains a non-TRAIN thread.")
    return tuple(clipped(first_spotify_reply(train_map[value]), maximum_chars) for value in ids)


def duration_seconds(value: str) -> float:
    total = 0.0
    for amount, unit in re.findall(r"([0-9]*\.?[0-9]+)(ms|s|m)", value):
        number = float(amount)
        total += number / 1000 if unit == "ms" else number * 60 if unit == "m" else number
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("configs/judge_v2.yaml"))
    parser.add_argument(
        "--sample-output", type=Path, default=Path("results/dev_judge_v2_sample_manifest.json")
    )
    parser.add_argument(
        "--results-output", type=Path, default=Path("results/dev_judge_v2_results.jsonl")
    )
    parser.add_argument(
        "--order-output", type=Path, default=Path("results/dev_judge_v2_order_bias.jsonl")
    )
    parser.add_argument(
        "--run-manifest-output",
        type=Path,
        default=Path("results/dev_judge_v2_run_manifest.json"),
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    split = json.loads(Path("data/manifests/split_manifest.json").read_text(encoding="utf-8"))
    development_ids, train_ids = set(split["thread_ids"]["DEVELOPMENT"]), set(
        split["thread_ids"]["TRAIN"]
    )
    frozen_manifest = Path("data/manifests/final_golden_candidate_manifest.json")
    relevant = development_ids | train_ids
    thread_map = {
        item.thread_id: item
        for item in read_threads(Path("data/processed/spotify_threads.jsonl"))
        if item.thread_id in relevant
    }
    proposed = read_jsonl(Path("results/dev_proposed_agent.jsonl"))
    manifest = prepare_manifest(
        config, proposed, thread_map, development_ids, frozen_manifest, args.sample_output
    )
    print(
        f"Prepared V2 cases={manifest['case_count']} AUTO_HANDLE={manifest['auto_handle_count']} "
        f"ESCALATE={manifest['escalate_count']}.",
        flush=True,
    )
    if args.prepare_only:
        return 0
    try:
        provider = provider_from_environment(config)
    except CredentialUnavailable as error:
        print(f"BLOCKED_ON_LLM_CREDENTIALS: {error}", file=sys.stderr)
        return 2
    systems = {
        "proposed": proposed,
        "lexical": read_jsonl(Path("results/dev_baseline_lexical.jsonl")),
        "fixed": read_jsonl(Path("results/dev_baseline_fixed.jsonl")),
    }
    indexed = {
        name: {str(item["case_id"]): item for item in rows} for name, rows in systems.items()
    }
    train_map = {case_id: thread_map[case_id] for case_id in train_ids}
    runner = V2JudgeRunner(
        provider, JudgeCache(Path(str(config["cache_directory"]))), config
    )
    sample_ids = [str(item["case_id"]) for item in manifest["cases"]]

    def call(system: str, case_id: str, replicate: str = "primary"):
        source = indexed[system][case_id]
        return runner.evaluate(
            case_id=case_id,
            customer=clipped(
                thread_map[case_id].customer_text(), int(config["customer_context_characters"])
            ),
            reply=clipped(str(source["reply"]), int(config["reply_characters"])),
            action=str(source["action"]),
            evidence=evidence_for(system, source, train_map, config),
            replicate=replicate,
        )

    if args.estimate_only:
        for case_id in manifest["estimation_case_ids"]:
            for system in ("proposed", "lexical", "fixed"):
                call(system, str(case_id))
        calls = int(config["estimation_case_count"]) * 3
        counted = runner.stats.total_tokens - runner.stats.cached_input_tokens
        average = counted / calls
        planned = int(config["development_sample_size"]) * 3 + (
            int(config["repeatability_sample_size"]) * 2
        ) + int(config["order_bias_sample_size"]) * 2
        projected = average * planned
        safe_budget = int(config["daily_token_budget"]) * float(
            config["daily_token_safety_fraction"]
        )
        print(
            json.dumps(
                {
                    "representative_calls": calls,
                    "stats": runner.stats.__dict__,
                    "average_counted_tokens": average,
                    "maximum_planned_calls": planned,
                    "projected_counted_tokens": projected,
                    "safe_daily_budget": safe_budget,
                    "fits_safe_budget": projected <= safe_budget,
                    "last_rate_limits": runner.last_rate_limits,
                },
                sort_keys=True,
            )
        )
        return 0 if projected <= safe_budget else 3

    records = []
    completed = 0
    planned = 280

    def checkpoint(stage: str) -> None:
        nonlocal completed
        counted = runner.stats.total_tokens - runner.stats.cached_input_tokens
        projected = counted / completed * planned if completed else 0
        safe_budget = int(config["daily_token_budget"]) * float(
            config["daily_token_safety_fraction"]
        )
        if completed >= 20 and projected > safe_budget:
            raise RuntimeError(
                f"Projected V2 tokens {projected:.0f} exceed safe budget {safe_budget:.0f}."
            )
        remaining = runner.last_rate_limits.get("x-ratelimit-remaining-tokens")
        if remaining and completed and float(remaining) < counted / completed * 1.2:
            wait = duration_seconds(runner.last_rate_limits.get("x-ratelimit-reset-tokens", ""))
            if wait:
                time.sleep(min(wait + 0.25, 60.0))
        if completed % 20 == 0:
            print(
                f"V2 progress stage={stage} completed={completed}/280 "
                f"provider_success={runner.stats.successful} cache_hits={runner.stats.cache_hits} "
                f"retries={runner.stats.retries} counted_tokens={counted}",
                flush=True,
            )

    for system in ("proposed", "lexical", "fixed"):
        for case_id in sample_ids:
            result = call(system, case_id)
            records.append(
                {
                    "protocol": config["version"],
                    "provider": config["provider"],
                    "judge_model": provider.model,
                    "rubric_version": config["rubric_version"],
                    "prompt_version": config["prompt_version"],
                    "case_id": case_id,
                    "system": system,
                    "run_id": "primary",
                    **result.as_dict(),
                }
            )
            completed += 1
            checkpoint("main")
    write_jsonl(args.results_output, records)
    for pass_number in (2, 3):
        for case_id in manifest["repeatability"]["case_ids"]:
            result = call("proposed", str(case_id), f"repeat-{pass_number}")
            records.append(
                {
                    "protocol": config["version"],
                    "provider": config["provider"],
                    "judge_model": provider.model,
                    "rubric_version": config["rubric_version"],
                    "prompt_version": config["prompt_version"],
                    "case_id": case_id,
                    "system": "proposed",
                    "run_id": f"repeat-{pass_number}",
                    **result.as_dict(),
                }
            )
            completed += 1
            checkpoint("repeatability")
    write_jsonl(args.results_output, records)
    order_records = []
    for case_id in manifest["order_bias"]["case_ids"]:
        case_id = str(case_id)
        proposed_item, lexical_item = indexed["proposed"][case_id], indexed["lexical"][case_id]
        proposed_first = stable_rank(f"{config['sample_seed']}:ab", case_id)[0] < "8"
        ordered = [proposed_item, lexical_item] if proposed_first else [lexical_item, proposed_item]
        evidence = evidence_for("proposed", proposed_item, train_map, config)
        for label, pair in (("first", ordered), ("swapped", list(reversed(ordered)))):
            result = runner.evaluate_pair(
                case_id=case_id,
                customer=clipped(
                    thread_map[case_id].customer_text(),
                    int(config["customer_context_characters"]),
                ),
                action_a=str(pair[0]["action"]),
                reply_a=clipped(str(pair[0]["reply"]), int(config["reply_characters"])),
                action_b=str(pair[1]["action"]),
                reply_b=clipped(str(pair[1]["reply"]), int(config["reply_characters"])),
                evidence=evidence,
                order=label,
            )
            order_records.append(
                {
                    "protocol": config["version"],
                    "provider": config["provider"],
                    "judge_model": provider.model,
                    "rubric_version": config["rubric_version"],
                    "prompt_version": config["pairwise_prompt_version"],
                    "case_id": case_id,
                    "order": label,
                    "a_system": "proposed" if pair[0] is proposed_item else "lexical",
                    "b_system": "proposed" if pair[1] is proposed_item else "lexical",
                    **result.__dict__,
                }
            )
            completed += 1
            checkpoint("order-bias")
    write_jsonl(args.order_output, order_records)
    write_json(
        args.run_manifest_output,
        {
            "phase": "5A",
            "protocol": config["version"],
            "phase5a_v1_status": config["phase5a_v1_status"],
            "phase5a_v2_reason": config["phase5a_v2_reason"],
            "v1_partial_results_used": False,
            "split": "DEVELOPMENT",
            "provider": config["provider"],
            "model": provider.model,
            "rubric_version": config["rubric_version"],
            "prompt_version": config["prompt_version"],
            "pairwise_prompt_version": config["pairwise_prompt_version"],
            "main_results": 240,
            "repeatability_additional_results": 24,
            "order_bias_results": 16,
            "validated_logical_judgments": 280,
            "overall_pass_source": "deterministically derived from validated rubric scores",
            "provider_calls": runner.stats.__dict__,
            "cumulative_judge_accounting": {
                "validated_judgments": 280,
                "retries": runner.stats.retries,
                "failures": runner.stats.failures,
                "pass_rule_corrections": runner.stats.pass_rule_corrections,
            },
            "token_efficiency": {
                "input_tokens": runner.stats.prompt_tokens,
                "cached_input_tokens": runner.stats.cached_input_tokens,
                "output_tokens": runner.stats.completion_tokens,
                "total_tokens": runner.stats.total_tokens,
                "counted_tokens": runner.stats.total_tokens
                - runner.stats.cached_input_tokens,
            },
            "last_rate_limits": runner.last_rate_limits,
            "frozen_evaluation_touched": False,
            "human_gold_used": 0,
            "ai_provisional_used_as_gold": False,
            "output_hashes": {
                "judge_results": sha256_file(args.results_output),
                "order_bias_raw": sha256_file(args.order_output),
            },
        },
    )
    print(json.dumps(runner.stats.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
