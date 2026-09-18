#!/usr/bin/env python3
"""Validate reproducible TRAIN-only Phase 4 intent-classifier fitting."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.classification.classifier import IntentClassifier  # noqa: E402
from support_agent.data.protection import assert_no_frozen_thread_ids  # noqa: E402
from support_agent.data.spotify import read_threads, write_json  # noqa: E402
from support_agent.taxonomy.discovery import provisional_intent  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def main() -> int:
    split_path = Path("data/manifests/split_manifest.json")
    frozen_path = Path("data/manifests/final_golden_candidate_manifest.json")
    ids = set(json.loads(split_path.read_text(encoding="utf-8"))["thread_ids"]["TRAIN"])
    assert_no_frozen_thread_ids(ids, frozen_path, "intent classifier training")
    taxonomy = load_taxonomy(Path("configs/taxonomy.yaml"))
    config = json.loads(Path("configs/agent.yaml").read_text(encoding="utf-8"))["classifier"]
    train = [
        thread
        for thread in read_threads(Path("data/processed/spotify_threads.jsonl"))
        if thread.thread_id in ids
    ]
    if len(train) != len(ids):
        raise ValueError("TRAIN IDs do not reconcile with the corpus.")
    classifier = IntentClassifier.fit(train, taxonomy, config)
    distribution = Counter(provisional_intent(item.customer_text(), taxonomy) for item in train)
    write_json(
        Path("results/intent_classifier_manifest.json"),
        {
            "phase": "4",
            "training_partition": "TRAIN",
            "training_examples": len(train),
            "classes": list(classifier.classes),
            "weak_label_distribution": dict(sorted(distribution.items())),
            "weak_label_cross_validation_used": False,
            "frozen_ids_used": False,
            "ai_provisional_labels_used": False,
        },
    )
    print(f"TRAIN examples fitted: {len(train)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
