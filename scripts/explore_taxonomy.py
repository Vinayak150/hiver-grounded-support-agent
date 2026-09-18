#!/usr/bin/env python3
"""Run deterministic train-only TF-IDF taxonomy exploration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.protection import assert_no_frozen_thread_ids  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.taxonomy.discovery import explore_taxonomy  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument("--splits", type=Path, default=Path("data/manifests/split_manifest.json"))
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument("--output", type=Path, default=Path("results/taxonomy_exploration.json"))
    parser.add_argument(
        "--frozen-manifest",
        type=Path,
        default=Path("data/manifests/final_golden_candidate_manifest.json"),
    )
    arguments = parser.parse_args()
    split_manifest = json.loads(arguments.splits.read_text(encoding="utf-8"))
    train_ids = set(split_manifest["thread_ids"]["TRAIN"])
    assert_no_frozen_thread_ids(train_ids, arguments.frozen_manifest, "taxonomy discovery")
    threads = [thread for thread in read_threads(arguments.corpus) if thread.thread_id in train_ids]
    if {thread.thread_id for thread in threads} != train_ids:
        raise ValueError("TRAIN IDs do not reconcile with the extracted corpus.")
    taxonomy = load_taxonomy(arguments.taxonomy)
    result = explore_taxonomy(threads, taxonomy)
    result.update(
        {
            "phase": "2",
            "brand": taxonomy.brand,
            "taxonomy_version": taxonomy.version,
            "source_split": taxonomy.source_split,
            "train_thread_count": len(threads),
            "train_thread_ids_sha256": hashlib.sha256(
                "\n".join(sorted(train_ids)).encode()
            ).hexdigest(),
            "split_manifest_sha256": sha256_file(arguments.splits),
        }
    )
    write_json(arguments.output, result)
    print(f"Train-only taxonomy rows: {len(threads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
