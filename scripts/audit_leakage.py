#!/usr/bin/env python3
"""Verify final exact and near-duplicate leakage across protected partitions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.leakage import (  # noqa: E402
    exact_cross_split_collisions,
    near_duplicate_pairs,
)
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument("--splits", type=Path, default=Path("data/manifests/split_manifest.json"))
    parser.add_argument("--config", type=Path, default=Path("configs/splits.yaml"))
    parser.add_argument("--output", type=Path, default=Path("data/manifests/leakage_audit.json"))
    arguments = parser.parse_args()
    split_manifest = json.loads(arguments.splits.read_text(encoding="utf-8"))
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    assignments = {
        thread_id: split
        for split, thread_ids in split_manifest["thread_ids"].items()
        for thread_id in thread_ids
    }
    threads = [
        thread for thread in read_threads(arguments.corpus) if thread.thread_id in assignments
    ]
    exact_config = config["exact_collision_policy"]
    near_config = config["near_duplicate_policy"]
    exact = exact_cross_split_collisions(
        threads,
        assignments,
        int(exact_config["customer_min_words"]),
        int(exact_config["brand_min_words"]),
    )
    near = near_duplicate_pairs(
        threads,
        assignments,
        float(near_config["token_jaccard_threshold"]),
        float(near_config["character_5gram_jaccard_threshold"]),
        int(near_config["minimum_tokens"]),
        int(near_config["bottom_k_signature_size"]),
    )
    payload = {
        "phase": "2",
        "split_version": split_manifest["version"],
        "split_manifest_sha256": sha256_file(arguments.splits),
        "thresholds": near_config,
        "exact_collisions_before_remediation": split_manifest["remediation"][
            "exact_collisions_discovered"
        ],
        "near_duplicates_before_remediation": split_manifest["remediation"][
            "near_duplicates_discovered"
        ],
        "remediation": (
            "Later-split conflicting threads were excluded before manifests "
            "and candidate sampling."
        ),
        "final_exact_collisions": exact,
        "final_near_duplicates": near,
        "protected_boundaries_clean": not exact and not near,
    }
    write_json(arguments.output, payload)
    if exact or near:
        raise SystemExit("Protected split boundaries still contain leakage.")
    print("Protected split boundaries clean: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
