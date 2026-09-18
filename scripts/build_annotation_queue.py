#!/usr/bin/env python3
"""Build a blinded deterministic candidate queue; create no human labels."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.queue import sample_candidates  # noqa: E402
from support_agent.annotation.schema import CANDIDATE_FIELDS, validate_candidate  # noqa: E402
from support_agent.annotation.store import AnnotationStore  # noqa: E402
from support_agent.data.spotify import read_threads  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument("--splits", type=Path, default=Path("data/manifests/split_manifest.json"))
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument("--config", type=Path, default=Path("configs/annotation.yaml"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/annotations/golden_candidates.csv")
    )
    parser.add_argument(
        "--annotations", type=Path, default=Path("data/annotations/golden_annotations.csv")
    )
    arguments = parser.parse_args()
    split_manifest = json.loads(arguments.splits.read_text(encoding="utf-8"))
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy(arguments.taxonomy)
    train_ids = set(split_manifest["thread_ids"]["TRAIN"])
    golden_ids = set(split_manifest["thread_ids"]["GOLDEN_CANDIDATE"])
    threads = list(read_threads(arguments.corpus))
    train = [thread for thread in threads if thread.thread_id in train_ids]
    golden = [thread for thread in threads if thread.thread_id in golden_ids]
    rows = sample_candidates(golden, train, taxonomy, config)
    if any(row.thread_id not in golden_ids or row.thread_id in train_ids for row in rows):
        raise ValueError("Candidate sampling violated the protected split contract.")
    for row in rows:
        validate_candidate(row)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CANDIDATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(row.__dict__ for row in rows)
    AnnotationStore(arguments.annotations).initialize()
    counts = Counter(row.sampling_bucket for row in rows)
    print(json.dumps(dict(sorted(counts.items())), sort_keys=True))
    print("Human labels created: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
