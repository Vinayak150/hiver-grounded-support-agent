#!/usr/bin/env python3
"""Create decontaminated temporal thread partitions and a committed ID manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.splits import (  # noqa: E402
    SPLITS,
    assert_no_overlap,
    decontaminate_assignments,
    random_assignments,
    temporal_assignments,
)
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402


def _time_ranges(threads: list, assignments: dict[str, str]) -> dict[str, dict[str, str]]:
    result = {}
    for split in SPLITS:
        values = sorted(
            thread.start_time for thread in threads if assignments.get(thread.thread_id) == split
        )
        result[split] = {"start": values[0], "end": values[-1]} if values else {}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument("--config", type=Path, default=Path("configs/splits.yaml"))
    parser.add_argument("--output", type=Path, default=Path("data/manifests/split_manifest.json"))
    arguments = parser.parse_args()
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    threads = list(read_threads(arguments.corpus))
    base = temporal_assignments(threads, config["ratios"])
    random = random_assignments(threads, config["ratios"], str(config["version"]))
    assignments, remediation = decontaminate_assignments(threads, base, config)
    assert_no_overlap(assignments)
    manifest = {
        "phase": "2",
        "version": config["version"],
        "brand": config["brand"],
        "strategy": config["strategy"],
        "rationale": (
            "Chronological order simulates later unseen support and avoids choosing "
            "a split based on model accuracy."
        ),
        "source_corpus_sha256": sha256_file(arguments.corpus),
        "configured_ratios": config["ratios"],
        "initial_temporal_counts": dict(sorted(Counter(base.values()).items())),
        "final_counts": dict(sorted(Counter(assignments.values()).items())),
        "time_ranges": _time_ranges(threads, assignments),
        "strategy_comparison": {
            "deterministic_random_counts": dict(sorted(Counter(random.values()).items())),
            "deterministic_random_time_ranges": _time_ranges(threads, random),
            "temporal_selected": True,
        },
        "thread_ids": {
            split: sorted(thread_id for thread_id, value in assignments.items() if value == split)
            for split in SPLITS
        },
        "remediation": remediation,
    }
    write_json(arguments.output, manifest)
    print(json.dumps(manifest["final_counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
