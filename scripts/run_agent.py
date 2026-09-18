#!/usr/bin/env python3
"""Run the proposed Phase 4 agent on DEVELOPMENT only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.agent.evidence import calibrate_thresholds  # noqa: E402
from support_agent.agent.orchestrator import GroundedSupportAgent  # noqa: E402
from support_agent.classification.classifier import IntentClassifier  # noqa: E402
from support_agent.data.protection import assert_no_frozen_thread_ids  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.retrieval.hybrid import HybridRetriever  # noqa: E402
from support_agent.taxonomy.discovery import provisional_intent  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def _quantiles(values: list[float]) -> dict[str, float]:
    return {
        str(value): round(float(np.quantile(values, value)), 6)
        for value in (0.0, 0.25, 0.5, 0.75, 1.0)
    }


def _ids_sha256(values: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()


def _write_outputs(path: Path, outputs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for output in outputs:
            stream.write(json.dumps(output.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument("--splits", type=Path, default=Path("data/manifests/split_manifest.json"))
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument("--config", type=Path, default=Path("configs/agent.yaml"))
    parser.add_argument(
        "--frozen-manifest",
        type=Path,
        default=Path("data/manifests/final_golden_candidate_manifest.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("results/dev_proposed_agent.jsonl"))
    parser.add_argument(
        "--manifest-output", type=Path, default=Path("results/dev_proposed_agent_manifest.json")
    )
    parser.add_argument(
        "--diagnostics-output", type=Path, default=Path("results/dev_agent_diagnostics.json")
    )
    arguments = parser.parse_args()

    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    split_manifest = json.loads(arguments.splits.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy(arguments.taxonomy)
    train_ids = set(split_manifest["thread_ids"]["TRAIN"])
    development_ids = set(split_manifest["thread_ids"]["DEVELOPMENT"])
    if train_ids & development_ids:
        raise ValueError("TRAIN and DEVELOPMENT IDs overlap.")
    assert_no_frozen_thread_ids(train_ids, arguments.frozen_manifest, "agent training")
    assert_no_frozen_thread_ids(development_ids, arguments.frozen_manifest, "agent calibration")
    needed = train_ids | development_ids
    thread_map = {
        thread.thread_id: thread
        for thread in read_threads(arguments.corpus)
        if thread.thread_id in needed
    }
    if set(thread_map) != needed:
        raise ValueError("TRAIN/DEVELOPMENT IDs do not reconcile with the corpus.")
    train = [thread_map[value] for value in sorted(train_ids)]
    development = [thread_map[value] for value in sorted(development_ids)]

    classifier = IntentClassifier.fit(train, taxonomy, config["classifier"])
    weak_labels = Counter(provisional_intent(thread.customer_text(), taxonomy) for thread in train)
    intent_predictions = classifier.predict_many(development)
    retriever = HybridRetriever.fit(train, taxonomy, config["retrieval"])
    retrievals = retriever.retrieve_many(
        development, [prediction.intent for prediction in intent_predictions]
    )
    thresholds = calibrate_thresholds(intent_predictions, retrievals, config["calibration"])
    agent = GroundedSupportAgent(classifier, retriever, thresholds, config)
    outputs = agent.run_many(development, intent_predictions, retrievals)
    _write_outputs(arguments.output, outputs)

    action_counts = Counter(output.action for output in outputs)
    intent_counts = Counter(output.intent for output in outputs)
    reason_counts = Counter(code for output in outputs for code in output.reason_codes)
    verifier_counts = Counter(
        code
        for output in outputs
        for code in output.reason_codes
        if code
        in {
            "GROUNDING_FAILURE",
            "PII_LEAK",
            "UNSUPPORTED_ACTION_CLAIM",
            "MISSING_EVIDENCE",
            "INVALID_EVIDENCE_REFERENCE",
        }
    )
    evidence_count = sum(output.evidence_sufficient for output in outputs)
    replies = [output.reply for output in outputs]
    diagnostics = {
        "phase": "4",
        "split": "DEVELOPMENT",
        "interpretation": "Engineering diagnostics only; no human-label accuracy claims.",
        "prediction_count": len(outputs),
        "predicted_intent_distribution": dict(sorted(intent_counts.items())),
        "intent_confidence_quantiles": _quantiles(
            [prediction.confidence for prediction in intent_predictions]
        ),
        "intent_margin_quantiles": _quantiles(
            [prediction.margin for prediction in intent_predictions]
        ),
        "action_distribution": dict(sorted(action_counts.items())),
        "action_rates": {
            key: round(value / len(outputs), 6) for key, value in sorted(action_counts.items())
        },
        "escalation_reason_distribution": dict(sorted(reason_counts.items())),
        "top_retrieval_score_quantiles": _quantiles(
            [items[0].evidence_score for items in retrievals]
        ),
        "top_customer_similarity_quantiles": _quantiles(
            [items[0].similarity for items in retrievals]
        ),
        "evidence_sufficient_count": evidence_count,
        "evidence_sufficient_rate": round(evidence_count / len(outputs), 6),
        "grounding_verifier_failure_distribution": dict(sorted(verifier_counts.items())),
        "reply_diversity": {
            "unique_replies": len(set(replies)),
            "unique_reply_rate": round(len(set(replies)) / len(replies), 6),
        },
        "latency": {
            "recorded": False,
            "reason": "Disabled so byte-identical deterministic artifacts can be verified.",
        },
    }
    write_json(arguments.diagnostics_output, diagnostics)

    with Path("data/annotations/golden_annotations.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        human_gold_count = sum(1 for row in csv.DictReader(stream) if row.get("status"))
    manifest = {
        "phase": "4",
        "brand": taxonomy.brand,
        "system_version": config["version"],
        "prediction_split": "DEVELOPMENT",
        "development_prediction_count": len(outputs),
        "train_partition_count": len(train),
        "classifier": {
            "model": "word+character TF-IDF with class-balanced LogisticRegression",
            "training_label_source": "TRAIN-side deterministic provisional taxonomy groups",
            "classes": list(classifier.classes),
            "weak_label_distribution": dict(sorted(weak_labels.items())),
            "weak_label_cross_validation_used": False,
        },
        "retriever": {
            "signals": list(config["retrieval"]["weights"]),
            "top_k": config["retrieval"]["top_k"],
            "corpus": retriever.corpus_stats,
        },
        "evidence_gate": {
            "thresholds": thresholds.as_dict(),
            "calibration_method": config["calibration"]["method"],
        },
        "source_hashes": {
            "corpus": sha256_file(arguments.corpus),
            "split_manifest": sha256_file(arguments.splits),
            "taxonomy": sha256_file(arguments.taxonomy),
            "agent_config": sha256_file(arguments.config),
            "train_ids": _ids_sha256(train_ids),
            "development_ids": _ids_sha256(development_ids),
        },
        "output_hashes": {
            "predictions": sha256_file(arguments.output),
            "diagnostics": sha256_file(arguments.diagnostics_output),
        },
        "protection": {
            "classifier_train_only": True,
            "retriever_train_only": True,
            "development_distribution_calibration_only": True,
            "frozen_evaluation_predictions_generated": False,
            "frozen_ids_used_for_optimization": False,
            "human_gold_labels_used": human_gold_count,
            "ai_provisional_labels_used": False,
            "headline_metrics_computed": False,
        },
    }
    write_json(arguments.manifest_output, manifest)
    print(f"DEVELOPMENT predictions: {len(outputs)}")
    print(f"AUTO_HANDLE: {action_counts['AUTO_HANDLE']}")
    print(f"ESCALATE: {action_counts['ESCALATE']}")
    print(f"TRAIN retrieval corpus: {retriever.corpus_stats['retrieval_corpus_threads']}")
    print("Frozen evaluation predictions generated: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
