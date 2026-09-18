#!/usr/bin/env python3
"""Extract the deterministic reconstructed SpotifyCares corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.spotify import extract_spotify_corpus  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/twcs.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/manifests/spotify_threads_manifest.json")
    )
    arguments = parser.parse_args()
    manifest = extract_spotify_corpus(arguments.input, arguments.output, arguments.manifest)
    print(f"Spotify relevant threads: {manifest['total_relevant_threads']}")
    print(f"Spotify usable threads: {manifest['usable_threads']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
