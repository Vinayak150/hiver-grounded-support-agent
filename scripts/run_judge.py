#!/usr/bin/env python3
"""Prepare and, when credentialed, run blinded Phase 5A DEVELOPMENT judging."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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
from support_agent.judge.runner import JudgeRunner  # noqa: E402
from support_agent.judge.sampling import build_development_sample, stable_rank  # noqa: E402
from support_agent.judge.schema import EvidenceExcerpt, JudgeInput  # noqa: E402


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


def prepare_manifest(config, proposed, thread_map, development_ids, frozen_manifest, output):
    sample = build_development_sample(
        proposed,
        thread_map,
        sample_size=int(config["development_sample_size"]),
        seed=str(config["sample_seed"]),
    )
    sample_ids = {str(item["case_id"]) for item in sample}
    if not sample_ids <= development_ids:
        raise ValueError("Judge sample contains a non-DEVELOPMENT case.")
    assert_no_frozen_thread_ids(sample_ids, frozen_manifest, "Phase 5A judge sampling")
    repeatability_ids = sorted(
        sample_ids, key=lambda value: stable_rank(f"{config['sample_seed']}:repeat", value)
    )[: int(config["repeatability_sample_size"])]
    order_bias_ids = sorted(
        sample_ids, key=lambda value: stable_rank(f"{config['sample_seed']}:order", value)
    )[: int(config["order_bias_sample_size"])]
    manifest = {
        "phase": "5A",
        "split": "DEVELOPMENT",
        "status": "SAMPLE_PREPARED",
        "sample_seed": config["sample_seed"],
        "sampling_method": (
            "All proposed AUTO_HANDLE cases plus stable-hash round-robin strata over "
            "intent, evidence sufficiency, risk presence, and lexical challenge flags."
        ),
        "case_count": len(sample),
        "auto_handle_count": sum(item["proposed_action"] == "AUTO_HANDLE" for item in sample),
        "auto_handle_population_count": sum(item["action"] == "AUTO_HANDLE" for item in proposed),
        "stratum_counts": dict(
            sorted(Counter(str(item["proposed_intent"]) for item in sample).items())
        ),
        "cases": sample,
        "repeatability": {
            "case_ids": repeatability_ids,
            "passes": config["repeatability_passes"],
        },
        "order_bias": {
            "case_ids": order_bias_ids,
            "first_order_rule": "Stable hash selects anonymous A/B; second call swaps order.",
        },
        "protection": {
            "development_only": True,
            "frozen_evaluation_judged": False,
            "human_gold_used": 0,
            "ai_provisional_used_as_gold": False,
        },
        "source_hashes": {
            "proposed_predictions": sha256_file(Path("results/dev_proposed_agent.jsonl")),
            "split_manifest": sha256_file(Path("data/manifests/split_manifest.json")),
            "judge_config": sha256_file(Path("configs/judge.yaml")),
        },
    }
    write_json(output, manifest)
    return manifest


def evidence_for(system, record, train_map, maximum):
    if system == "proposed":
        ids = {str(item["thread_id"]) for item in record["retrieved_cases"]}
        if not ids <= set(train_map):
            raise ValueError("Proposed judge evidence contains a non-TRAIN thread.")
        return tuple(
            EvidenceExcerpt(str(item["thread_id"]), str(item["historical_reply"])[:maximum])
            for item in record["retrieved_cases"]
        )
    ids = record.get("retrieved_thread_ids", [])
    if not set(ids) <= set(train_map):
        raise ValueError("Baseline judge evidence contains a non-TRAIN thread.")
    return tuple(
        EvidenceExcerpt(
            value, sanitize_public_text(first_spotify_reply(train_map[value]))[:maximum]
        )
        for value in ids
        if value in train_map
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("configs/judge.yaml"))
    parser.add_argument(
        "--sample-output", type=Path, default=Path("results/dev_judge_sample_manifest.json")
    )
    parser.add_argument(
        "--results-output", type=Path, default=Path("results/dev_judge_results.jsonl")
    )
    parser.add_argument(
        "--order-output", type=Path, default=Path("results/dev_judge_order_bias.jsonl")
    )
    arguments = parser.parse_args()
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    split_manifest = json.loads(
        Path("data/manifests/split_manifest.json").read_text(encoding="utf-8")
    )
    development_ids = set(split_manifest["thread_ids"]["DEVELOPMENT"])
    train_ids = set(split_manifest["thread_ids"]["TRAIN"])
    frozen_manifest = Path("data/manifests/final_golden_candidate_manifest.json")
    assert_no_frozen_thread_ids(development_ids, frozen_manifest, "Phase 5A DEVELOPMENT")
    relevant = development_ids | train_ids
    thread_map = {
        item.thread_id: item
        for item in read_threads(Path("data/processed/spotify_threads.jsonl"))
        if item.thread_id in relevant
    }
    proposed = read_jsonl(Path("results/dev_proposed_agent.jsonl"))
    manifest = prepare_manifest(
        config, proposed, thread_map, development_ids, frozen_manifest, arguments.sample_output
    )
    print(
        f"Prepared {manifest['case_count']} DEVELOPMENT cases; "
        f"AUTO_HANDLE coverage {manifest['auto_handle_count']}/"
        f"{manifest['auto_handle_population_count']}."
    )
    if arguments.prepare_only:
        return 0
    try:
        provider = provider_from_environment(config)
    except CredentialUnavailable as error:
        print(f"BLOCKED_ON_LLM_CREDENTIALS: {error}", file=sys.stderr)
        return 2

    systems = {
        "fixed": read_jsonl(Path("results/dev_baseline_fixed.jsonl")),
        "lexical": read_jsonl(Path("results/dev_baseline_lexical.jsonl")),
        "proposed": proposed,
    }
    indexed = {
        name: {str(item["case_id"]): item for item in rows} for name, rows in systems.items()
    }
    train_map = {case_id: thread_map[case_id] for case_id in train_ids}
    runner = JudgeRunner(provider, JudgeCache(Path(str(config["cache_directory"]))), config)
    records = []
    sample_ids = [str(item["case_id"]) for item in manifest["cases"]]
    for system, rows in indexed.items():
        for case_id in sample_ids:
            source = rows[case_id]
            item = JudgeInput(
                case_id=case_id,
                customer_context=sanitize_public_text(thread_map[case_id].customer_text()),
                reply=str(source["reply"]),
                action=str(source["action"]),
                evidence=evidence_for(
                    system, source, train_map, int(config["evidence_excerpt_characters"])
                ),
            )
            result = runner.evaluate(item)
            records.append({"system": system, "run_id": "primary", **result.as_dict()})
    for pass_number in range(2, int(config["repeatability_passes"]) + 1):
        for case_id in manifest["repeatability"]["case_ids"]:
            source = indexed["proposed"][case_id]
            item = JudgeInput(
                case_id=case_id,
                customer_context=sanitize_public_text(thread_map[case_id].customer_text()),
                reply=str(source["reply"]),
                action=str(source["action"]),
                evidence=evidence_for(
                    "proposed", source, train_map, int(config["evidence_excerpt_characters"])
                ),
            )
            result = runner.evaluate(item, replicate=f"repeat-{pass_number}")
            records.append(
                {"system": "proposed", "run_id": f"repeat-{pass_number}", **result.as_dict()}
            )
    write_jsonl(arguments.results_output, records)
    # Pairwise calls are deliberately separated; system identity is attached only after return.
    order_records = []
    for case_id in manifest["order_bias"]["case_ids"]:
        lexical = indexed["lexical"][case_id]
        proposed_item = indexed["proposed"][case_id]
        proposed_first = stable_rank(f"{config['sample_seed']}:ab", case_id)[0] < "8"
        ordered = [proposed_item, lexical] if proposed_first else [lexical, proposed_item]
        evidence = evidence_for(
            "proposed", proposed_item, train_map, int(config["evidence_excerpt_characters"])
        )
        base = {
            "case_id": case_id,
            "customer_context": sanitize_public_text(thread_map[case_id].customer_text()),
            "evidence": [
                {"evidence_id": value.evidence_id, "excerpt": value.excerpt} for value in evidence
            ],
        }
        for label, pair in (("first", ordered), ("swapped", list(reversed(ordered)))):
            payload = {
                **base,
                "action_a": str(pair[0]["action"]),
                "reply_a": str(pair[0]["reply"]),
                "action_b": str(pair[1]["action"]),
                "reply_b": str(pair[1]["reply"]),
            }
            result = runner.evaluate_pair(payload, order=label)
            order_records.append(
                {
                    "order": label,
                    "a_system": "proposed" if pair[0] is proposed_item else "lexical",
                    "b_system": "proposed" if pair[1] is proposed_item else "lexical",
                    **result.__dict__,
                }
            )
    write_jsonl(arguments.order_output, order_records)
    print(json.dumps(runner.stats.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
