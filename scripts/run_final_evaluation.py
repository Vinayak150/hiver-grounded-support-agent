#!/usr/bin/env python3
"""Run the frozen benchmark once genuine human gold passes every gate."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.agent.config import load_agent_config  # noqa: E402
from support_agent.agent.evidence import calibrate_thresholds  # noqa: E402
from support_agent.agent.orchestrator import GroundedSupportAgent  # noqa: E402
from support_agent.annotation.store import (  # noqa: E402
    AnnotationStore,
    load_frozen_candidates,
)
from support_agent.baselines.fixed import FixedBaseline  # noqa: E402
from support_agent.baselines.lexical import (  # noqa: E402
    LexicalBaseline,
    calibrate_similarity_threshold,
)
from support_agent.classification.classifier import IntentClassifier  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.evaluation.bootstrap import percentile_bootstrap_ci  # noqa: E402
from support_agent.evaluation.gold import validate_human_gold  # noqa: E402
from support_agent.evaluation.metrics import (  # noqa: E402
    action_metrics,
    correct_and_safe_automation_coverage,
    intent_classification_metrics,
)
from support_agent.retrieval.hybrid import HybridRetriever  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _bootstrap_metric(
    gold: list[str],
    predicted: list[str],
    statistic: Callable[[list[str], list[str]], float],
    seed: int,
) -> dict[str, int | float]:
    indices = list(range(len(gold)))
    return percentile_bootstrap_ci(
        indices,
        lambda sample: statistic(
            [gold[int(index)] for index in sample],
            [predicted[int(index)] for index in sample],
        ),
        samples=2000,
        seed=seed,
    )


def _intent_results(gold: list[str], predicted: list[str], labels: list[str]) -> dict[str, object]:
    result = intent_classification_metrics(gold, predicted, labels)
    result["bootstrap_95_ci"] = {
        "accuracy": _bootstrap_metric(
            gold,
            predicted,
            lambda left, right: float(
                intent_classification_metrics(left, right, labels)["accuracy"]
            ),
            20261101,
        ),
        "macro_f1": _bootstrap_metric(
            gold,
            predicted,
            lambda left, right: float(
                intent_classification_metrics(left, right, labels)["macro_f1"]
            ),
            20261102,
        ),
        "weighted_f1": _bootstrap_metric(
            gold,
            predicted,
            lambda left, right: float(
                intent_classification_metrics(left, right, labels)["weighted_f1"]
            ),
            20261103,
        ),
    }
    return result


def _action_results(gold: list[str], predicted: list[str]) -> dict[str, object]:
    result = action_metrics(gold, predicted)
    extractors: dict[str, Callable[[dict[str, object]], float]] = {
        "escalation_precision": lambda value: float(value["escalation_precision"]["value"]),
        "escalation_recall": lambda value: float(value["escalation_recall"]["value"]),
        "escalation_f1": lambda value: float(value["escalation_f1"]),
        "false_escalation_rate": lambda value: float(value["false_escalation_rate"]["value"]),
        "missed_escalation_rate": lambda value: float(value["missed_escalation_rate"]["value"]),
        "unsafe_auto_handle_rate": lambda value: float(value["unsafe_auto_handle_rate"]["value"]),
        "automation_coverage": lambda value: float(value["automation_coverage"]["value"]),
    }
    result["bootstrap_95_ci"] = {
        name: _bootstrap_metric(
            gold,
            predicted,
            lambda left, right, getter=getter: getter(action_metrics(left, right)),
            20261200 + offset,
        )
        for offset, (name, getter) in enumerate(extractors.items(), start=1)
    }
    return result


def _slices(
    case_ids: list[str],
    gold_intents: list[str],
    predicted_intents: list[str],
    gold_actions: list[str],
    predicted_actions: list[str],
) -> dict[str, object]:
    def summarize(indices: list[int]) -> dict[str, object]:
        return {
            "count": len(indices),
            "intent_accuracy": sum(
                gold_intents[index] == predicted_intents[index] for index in indices
            )
            / len(indices),
            "action_accuracy": sum(
                gold_actions[index] == predicted_actions[index] for index in indices
            )
            / len(indices),
            "automation_coverage": sum(
                predicted_actions[index] == "AUTO_HANDLE" for index in indices
            )
            / len(indices),
            "case_ids": [case_ids[index] for index in indices],
        }

    return {
        "by_gold_intent": {
            label: summarize([index for index, value in enumerate(gold_intents) if value == label])
            for label in sorted(set(gold_intents))
        },
        "by_gold_action": {
            label: summarize([index for index, value in enumerate(gold_actions) if value == label])
            for label in sorted(set(gold_actions))
        },
    }


def _load_response_quality(path: Path, required_case_ids: set[str]) -> dict[str, bool]:
    if not required_case_ids:
        return {}
    if not path.exists():
        raise ValueError(
            "Human response-quality evidence is required for every proposed AUTO_HANDLE case."
        )
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = (
            "case_id",
            "response_quality_approved",
            "reason",
            "annotation_source",
            "status",
        )
        if tuple(reader.fieldnames or ()) != expected:
            raise ValueError("Human response-quality evidence schema is invalid.")
        rows = list(reader)
    if len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("Human response-quality evidence contains duplicate case IDs.")
    output: dict[str, bool] = {}
    for row in rows:
        if row["case_id"] not in required_case_ids:
            continue
        if row["annotation_source"] != "human" or row["status"] != "FINALIZED":
            raise ValueError("Response-quality evidence must be finalized explicit human review.")
        normalized = row["response_quality_approved"].strip().casefold()
        if normalized not in {"true", "false"} or not row["reason"].strip():
            raise ValueError("Response-quality rows require a boolean decision and reason.")
        output[row["case_id"]] = normalized == "true"
    missing = required_case_ids - set(output)
    if missing:
        raise ValueError(
            f"Human response-quality evidence is missing for {len(missing)} AUTO_HANDLE cases."
        )
    return output


def _remap(
    row: dict[str, object], thread_to_case: dict[str, str], system: str
) -> dict[str, object]:
    payload = dict(row)
    payload["case_id"] = thread_to_case[str(row["case_id"])]
    payload["system_name"] = system
    return payload


def load_frozen_partitions(
    corpus: Path, paths: dict[str, Path]
) -> tuple[object, list[object], dict[str, str], list[object], list[object], list[object], dict]:
    """Load the protected partitions and verify the frozen Phase 4 system contract."""

    final_system_path = Path("data/manifests/final_system_manifest.json")
    final_system = json.loads(final_system_path.read_text(encoding="utf-8"))
    if (
        final_system["final_system_version"]
        != "spotify-grounded-agent-v1.0-final-candidate"
        or final_system["retained_candidate"] != "ORIGINAL_PHASE_4"
        or final_system["phase41_status"] != "REJECTED"
        or final_system["file_hashes"]["agent_config"]
        != sha256_file(Path("configs/agent.yaml"))
    ):
        raise ValueError("The frozen original Phase 4 final-system contract is invalid.")

    taxonomy = load_taxonomy(paths["taxonomy"])
    candidates = load_frozen_candidates(paths["candidates"])
    thread_to_case = {candidate.thread_id: candidate.case_id for candidate in candidates}
    split_manifest = json.loads(paths["splits"].read_text(encoding="utf-8"))
    train_ids = set(split_manifest["thread_ids"]["TRAIN"])
    development_ids = set(split_manifest["thread_ids"]["DEVELOPMENT"])
    final_ids = set(thread_to_case)
    if train_ids & development_ids or (train_ids | development_ids) & final_ids:
        raise ValueError("Protected TRAIN/DEVELOPMENT/frozen partitions overlap.")
    needed = train_ids | development_ids | final_ids
    thread_map = {
        thread.thread_id: thread for thread in read_threads(corpus) if thread.thread_id in needed
    }
    if set(thread_map) != needed:
        raise ValueError("Protected partitions do not reconcile with the processed corpus.")
    train = [thread_map[value] for value in sorted(train_ids)]
    development = [thread_map[value] for value in sorted(development_ids)]
    final = [thread_map[candidate.thread_id] for candidate in candidates]
    return (
        taxonomy,
        candidates,
        thread_to_case,
        train,
        development,
        final,
        final_system,
    )


def generate_final_proposed_predictions(
    train,
    development,
    final,
    taxonomy,
    final_system: dict,
    thread_to_case: dict[str, str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Generate the exact frozen proposed outputs and human-review details."""

    agent_config = load_agent_config(Path("configs/agent.yaml"))
    classifier = IntentClassifier.fit(train, taxonomy, agent_config["classifier"])
    retriever = HybridRetriever.fit(train, taxonomy, agent_config["retrieval"])
    dev_intents = classifier.predict_many(development)
    dev_retrievals = retriever.retrieve_many(
        development, [prediction.intent for prediction in dev_intents]
    )
    thresholds = calibrate_thresholds(dev_intents, dev_retrievals, agent_config["calibration"])
    if thresholds.as_dict() != final_system["development_only_calibrated_thresholds"]:
        raise ValueError("Agent DEVELOPMENT thresholds no longer match the final-system manifest.")
    final_intents = classifier.predict_many(final)
    final_retrievals = retriever.retrieve_many(
        final, [prediction.intent for prediction in final_intents]
    )
    agent = GroundedSupportAgent(classifier, retriever, thresholds, agent_config)
    agent_outputs = agent.run_many(final, final_intents, final_retrievals)
    proposed_rows = [
        _remap(
            output.to_prediction().as_dict(),
            thread_to_case,
            "spotify-grounded-agent-v1.0-final-candidate",
        )
        for output in agent_outputs
    ]
    review_rows = []
    for output, prediction in zip(agent_outputs, proposed_rows, strict=True):
        detail = output.as_dict()
        detail["case_id"] = prediction["case_id"]
        detail["system_version"] = prediction["system_name"]
        detail["evidence_ids"] = prediction["evidence_ids"]
        review_rows.append(detail)
    return proposed_rows, review_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument(
        "--gold", type=Path, default=Path("data/annotations/golden_annotations.csv")
    )
    parser.add_argument(
        "--response-quality",
        type=Path,
        default=Path("data/annotations/human_response_quality.csv"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("results/final"))
    arguments = parser.parse_args()

    paths = {
        "candidates": Path("data/annotations/final_golden_candidates.csv"),
        "frozen_manifest": Path("data/manifests/final_golden_candidate_manifest.json"),
        "splits": Path("data/manifests/split_manifest.json"),
        "taxonomy": Path("configs/taxonomy.yaml"),
        "annotation": Path("configs/annotation.yaml"),
    }
    gate = validate_human_gold(
        gold_path=arguments.gold,
        candidates_path=paths["candidates"],
        frozen_manifest_path=paths["frozen_manifest"],
        split_manifest_path=paths["splits"],
        taxonomy_path=paths["taxonomy"],
        annotation_config_path=paths["annotation"],
    )
    if not gate.final_evaluation_ready:
        print("FINAL_EVALUATION_READY=NO")
        print(f"HUMAN_LABEL_COUNT={gate.human_label_count}")
        print("FINAL_EVAL_BLOCKED=" + json.dumps(list(gate.errors)))
        return 2
    if not arguments.corpus.exists():
        print(f"FINAL_EVAL_BLOCKED=processed corpus missing: {arguments.corpus}")
        return 2

    final_system_path = Path("data/manifests/final_system_manifest.json")
    (
        taxonomy,
        candidates,
        thread_to_case,
        train,
        development,
        final,
        final_system,
    ) = load_frozen_partitions(arguments.corpus, paths)

    baseline_config = json.loads(Path("configs/baselines.yaml").read_text(encoding="utf-8"))
    fixed = FixedBaseline(baseline_config["fixed"])
    fixed_rows = [
        _remap(fixed.predict(thread).as_dict(), thread_to_case, fixed.system_name)
        for thread in final
    ]
    lexical = LexicalBaseline.fit(train, taxonomy, baseline_config["lexical"])
    dev_neighbors = lexical.retrieve_many(development)
    calibration = calibrate_similarity_threshold(
        [items[0].score for items in dev_neighbors], baseline_config["lexical"]
    )
    development_baselines = json.loads(
        Path("results/dev_baseline_manifest.json").read_text(encoding="utf-8")
    )
    if calibration.threshold != development_baselines["lexical_baseline"]["calibration"][
        "threshold"
    ]:
        raise ValueError("Lexical DEVELOPMENT calibration no longer matches its frozen manifest.")
    final_neighbors = lexical.retrieve_many(final)
    lexical_rows = [
        _remap(
            lexical.predict(thread, neighbors, calibration).as_dict(),
            thread_to_case,
            str(baseline_config["lexical"]["system_name"]),
        )
        for thread, neighbors in zip(final, final_neighbors, strict=True)
    ]

    proposed_rows, _ = generate_final_proposed_predictions(
        train,
        development,
        final,
        taxonomy,
        final_system,
        thread_to_case,
    )

    gold = AnnotationStore(arguments.gold).load()
    ordered_case_ids = [candidate.case_id for candidate in candidates if candidate.case_id in gold]
    proposed_by_id = {str(row["case_id"]): row for row in proposed_rows}
    required_quality = {
        case_id
        for case_id in ordered_case_ids
        if proposed_by_id[case_id]["action"] == "AUTO_HANDLE"
    }
    try:
        quality = _load_response_quality(arguments.response_quality, required_quality)
    except ValueError as error:
        print("FINAL_EVALUATION_READY=NO")
        print(f"FINAL_EVAL_BLOCKED={error}")
        return 2

    systems = {
        "fixed": fixed_rows,
        "lexical": lexical_rows,
        "proposed": proposed_rows,
    }
    gold_intents = [gold[case_id].gold_intent for case_id in ordered_case_ids]
    gold_actions = [gold[case_id].gold_action for case_id in ordered_case_ids]
    comparison: dict[str, object] = {
        "phase": "FINAL_EVALUATION",
        "status": "COMPLETE",
        "headline_status": "HUMAN_GOLD_BENCHMARK_COMPLETE",
        "final_system": final_system["final_system_version"],
        "human_gold_count": len(ordered_case_ids),
        "frozen_candidate_count": len(candidates),
        "bootstrap_samples": 2000,
        "systems": {},
    }
    for name, rows in systems.items():
        by_id = {str(row["case_id"]): row for row in rows}
        predicted_intents = [str(by_id[case_id]["intent"]) for case_id in ordered_case_ids]
        predicted_actions = [str(by_id[case_id]["action"]) for case_id in ordered_case_ids]
        payload = {
            "intent": _intent_results(gold_intents, predicted_intents, list(taxonomy.intent_ids)),
            "action": _action_results(gold_actions, predicted_actions),
            "slices": _slices(
                ordered_case_ids,
                gold_intents,
                predicted_intents,
                gold_actions,
                predicted_actions,
            ),
        }
        if name == "proposed":
            payload["correct_and_safe_automation_coverage"] = (
                correct_and_safe_automation_coverage(
                    gold_intents,
                    predicted_intents,
                    gold_actions,
                    predicted_actions,
                    [quality.get(case_id, False) for case_id in ordered_case_ids],
                )
            )
        comparison["systems"][name] = payload

    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in systems.items():
        _write_jsonl(arguments.output_dir / f"{name}_predictions.jsonl", rows)
    comparison["source_hashes"] = {
        "human_gold": sha256_file(arguments.gold),
        "response_quality": sha256_file(arguments.response_quality),
        "frozen_candidates": sha256_file(paths["candidates"]),
        "final_system_manifest": sha256_file(final_system_path),
    }
    write_json(arguments.output_dir / "comparison.json", comparison)
    print("FINAL_EVALUATION_READY=YES")
    print(f"HUMAN_LABEL_COUNT={len(ordered_case_ids)}")
    print(f"OUTPUT={arguments.output_dir / 'comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
