#!/usr/bin/env python3
"""Freeze exactly 200 unlabeled final evaluation candidates."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.freeze import freeze_candidates  # noqa: E402
from support_agent.annotation.schema import (  # noqa: E402
    FROZEN_CANDIDATE_FIELDS,
    validate_frozen_candidate,
)
from support_agent.annotation.store import load_candidates  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates", type=Path, default=Path("data/annotations/golden_candidates.csv")
    )
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument("--splits", type=Path, default=Path("data/manifests/split_manifest.json"))
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument("--config", type=Path, default=Path("configs/evaluation_freeze.yaml"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/annotations/final_golden_candidates.csv")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/final_golden_candidate_manifest.json"),
    )
    arguments = parser.parse_args()
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    split_manifest = json.loads(arguments.splits.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy(arguments.taxonomy)
    candidates = load_candidates(arguments.candidates)
    candidate_ids = {case.thread_id for case in candidates}
    threads = [
        thread for thread in read_threads(arguments.corpus) if thread.thread_id in candidate_ids
    ]
    frozen, evidence = freeze_candidates(candidates, threads, taxonomy, config)
    for case in frozen:
        validate_frozen_candidate(case)
    frozen_ids = {case.thread_id for case in frozen}
    train_ids = set(split_manifest["thread_ids"]["TRAIN"])
    development_ids = set(split_manifest["thread_ids"]["DEVELOPMENT"])
    golden_ids = set(split_manifest["thread_ids"]["GOLDEN_CANDIDATE"])
    if not frozen_ids <= golden_ids or frozen_ids & (train_ids | development_ids):
        raise ValueError("Frozen cases violated the protected split contract.")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FROZEN_CANDIDATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(case.__dict__ for case in frozen)
    manifest = {
        "phase": "2.6",
        "golden_set_status_at_creation": "AWAITING_HUMAN_CONFIRMATION",
        "human_confirmations_at_creation": 0,
        "brand": taxonomy.brand,
        "freeze_version": config["freeze_version"],
        "selection_seed": config["seed"],
        "taxonomy_version": taxonomy.version,
        "split_version": split_manifest["version"],
        "sampling_version": frozen[0].sampling_version,
        "source_candidate_sha256": sha256_file(arguments.candidates),
        "source_corpus_sha256": sha256_file(arguments.corpus),
        "source_split_manifest_sha256": sha256_file(arguments.splits),
        "final_candidate_sha256": sha256_file(arguments.output),
        "case_count": len(frozen),
        "candidate_type_counts": dict(
            sorted(Counter(case.candidate_type for case in frozen).items())
        ),
        "time_range": {
            "start": min(case.timestamp for case in frozen),
            "end": max(case.timestamp for case in frozen),
        },
        "thread_ids": [case.thread_id for case in frozen],
        "case_ids": [case.case_id for case in frozen],
        "protected_from": [
            "training",
            "retrieval",
            "few_shot_examples",
            "prompt_demonstrations",
            "development_tuning",
            "taxonomy_tuning",
        ],
        "selection_evidence": evidence,
    }
    write_json(arguments.manifest, manifest)
    print(json.dumps(manifest["candidate_type_counts"], sort_keys=True))
    print("Gold labels created: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
