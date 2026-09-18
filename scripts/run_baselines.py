#!/usr/bin/env python3
"""Generate deterministic Phase 3 baseline predictions for DEVELOPMENT only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.baselines.fixed import FixedBaseline  # noqa: E402
from support_agent.baselines.lexical import (  # noqa: E402
    LexicalBaseline,
    calibrate_similarity_threshold,
)
from support_agent.data.protection import assert_no_frozen_thread_ids  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.evaluation.schemas import Prediction  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def _write_predictions(path: Path, predictions: list[Prediction]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for prediction in predictions:
            payload = json.dumps(prediction.as_dict(), ensure_ascii=False, sort_keys=True)
            stream.write(payload + "\n")


def _ids_sha256(values: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument("--splits", type=Path, default=Path("data/manifests/split_manifest.json"))
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument("--config", type=Path, default=Path("configs/baselines.yaml"))
    parser.add_argument(
        "--frozen-manifest",
        type=Path,
        default=Path("data/manifests/final_golden_candidate_manifest.json"),
    )
    parser.add_argument(
        "--fixed-output", type=Path, default=Path("results/dev_baseline_fixed.jsonl")
    )
    parser.add_argument(
        "--lexical-output", type=Path, default=Path("results/dev_baseline_lexical.jsonl")
    )
    parser.add_argument(
        "--manifest-output", type=Path, default=Path("results/dev_baseline_manifest.json")
    )
    arguments = parser.parse_args()
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    split_manifest = json.loads(arguments.splits.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy(arguments.taxonomy)
    train_ids = set(split_manifest["thread_ids"]["TRAIN"])
    development_ids = set(split_manifest["thread_ids"]["DEVELOPMENT"])
    if train_ids & development_ids:
        raise ValueError("TRAIN and DEVELOPMENT thread IDs overlap.")
    assert_no_frozen_thread_ids(train_ids, arguments.frozen_manifest, "baseline training")
    assert_no_frozen_thread_ids(development_ids, arguments.frozen_manifest, "baseline calibration")
    relevant_ids = train_ids | development_ids
    threads = [
        thread for thread in read_threads(arguments.corpus) if thread.thread_id in relevant_ids
    ]
    thread_map = {thread.thread_id: thread for thread in threads}
    if set(thread_map) != relevant_ids:
        raise ValueError("TRAIN/DEVELOPMENT IDs do not reconcile with the extracted corpus.")
    train = [thread_map[thread_id] for thread_id in sorted(train_ids)]
    development = [thread_map[thread_id] for thread_id in sorted(development_ids)]

    fixed = FixedBaseline(config["fixed"])
    if fixed.intent not in taxonomy.intent_ids:
        raise ValueError("Fixed baseline intent is absent from the frozen taxonomy.")
    fixed_predictions = [fixed.predict(thread) for thread in development]

    lexical = LexicalBaseline.fit(train, taxonomy, config["lexical"])
    neighbors = lexical.retrieve_many(development)
    top_scores = [items[0].score for items in neighbors]
    calibration = calibrate_similarity_threshold(top_scores, config["lexical"])
    lexical_predictions = [
        lexical.predict(thread, retrieved, calibration)
        for thread, retrieved in zip(development, neighbors, strict=True)
    ]
    _write_predictions(arguments.fixed_output, fixed_predictions)
    _write_predictions(arguments.lexical_output, lexical_predictions)
    score_quantiles = {
        str(quantile): round(float(np.quantile(top_scores, quantile)), 6)
        for quantile in (0.0, 0.25, 0.5, 0.75, 1.0)
    }
    manifest = {
        "phase": "3",
        "brand": taxonomy.brand,
        "baseline_version": config["version"],
        "prediction_split": "DEVELOPMENT",
        "development_prediction_count": len(development),
        "train_partition_count": len(train),
        "train_retrieval_corpus": lexical.corpus_stats,
        "fixed_baseline": {
            "system_name": config["fixed"]["system_name"],
            "fixed_intent": fixed.intent,
            "intent_source": fixed.intent_source,
            "action": "ESCALATE",
            "prediction_count": len(fixed_predictions),
            "output_sha256": sha256_file(arguments.fixed_output),
        },
        "lexical_baseline": {
            "system_name": config["lexical"]["system_name"],
            "features": "word (1,2) and character (3,5) TF-IDF cosine similarity",
            "top_k": config["lexical"]["top_k"],
            "calibration": {
                "method": (
                    "Configured DEVELOPMENT top-1 similarity quantile, bounded by fixed "
                    "floors/ceilings; no labels or accuracy optimization."
                ),
                **calibration.__dict__,
                "top_similarity_quantiles": score_quantiles,
            },
            "predicted_action_distribution": dict(
                sorted(Counter(item.action for item in lexical_predictions).items())
            ),
            "prediction_count": len(lexical_predictions),
            "output_sha256": sha256_file(arguments.lexical_output),
        },
        "source_corpus_sha256": sha256_file(arguments.corpus),
        "source_split_manifest_sha256": sha256_file(arguments.splits),
        "train_thread_ids_sha256": _ids_sha256(train_ids),
        "development_thread_ids_sha256": _ids_sha256(development_ids),
        "frozen_evaluation_predictions_generated": False,
        "human_gold_labels_used": 0,
        "ai_provisional_labels_used_as_gold": False,
        "headline_metrics_computed": False,
    }
    write_json(arguments.manifest_output, manifest)
    print(f"Fixed DEVELOPMENT predictions: {len(fixed_predictions)}")
    print(f"Lexical DEVELOPMENT predictions: {len(lexical_predictions)}")
    print(f"TRAIN retrieval corpus: {lexical.corpus_stats['retrieval_corpus_threads']}")
    print(f"Heuristic similarity threshold: {calibration.threshold:.6f}")
    print("Frozen evaluation predictions generated: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
