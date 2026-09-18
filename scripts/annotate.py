#!/usr/bin/env python3
"""Blinded, resumable CLI for explicit human golden-set annotation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.schema import (  # noqa: E402
    build_human_annotation,
    validate_annotation,
)
from support_agent.annotation.store import AnnotationStore, load_candidates  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def _choose(prompt: str, values: tuple[str, ...]) -> str:
    print(" / ".join(values))
    value = input(prompt).strip()
    if value not in values:
        raise ValueError(f"Invalid value: {value}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates", type=Path, default=Path("data/annotations/golden_candidates.csv")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/annotations/golden_annotations.csv")
    )
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.yaml"))
    parser.add_argument("--config", type=Path, default=Path("configs/annotation.yaml"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--progress", action="store_true")
    arguments = parser.parse_args()
    candidates = load_candidates(arguments.candidates)
    taxonomy = load_taxonomy(arguments.taxonomy)
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    store = AnnotationStore(arguments.output)
    store.initialize()
    completed, total, next_case = store.progress(candidates)
    if arguments.progress:
        print(f"Progress: {completed}/{total}; next={next_case}")
        return 0
    count = 0
    for case in candidates:
        if case.case_id in store.load():
            continue
        if arguments.limit is not None and count >= arguments.limit:
            break
        print(f"\n[{case.case_id}] {completed + count + 1}/{total}")
        print(case.customer_message)
        print(f"Context: {case.conversation_context}")
        command = input("Annotate [a], defer [d], or quit [q]: ").strip().casefold()
        if command == "q":
            break
        if command == "d":
            continue
        if command != "a":
            print("Unknown command; case not saved.")
            continue
        values = {
            "gold_intent": _choose("Intent: ", taxonomy.intent_ids),
            "gold_action": _choose("Action: ", tuple(config["actions"])),
            "difficulty": _choose("Difficulty: ", tuple(config["difficulties"])),
            "risk_tags": input("Risk tags separated by | (blank allowed): ").strip(),
            "gold_action_reason": input("Short action reason: ").strip(),
            "annotation_notes": input("Optional notes: ").strip(),
        }
        annotation = build_human_annotation(case, explicit_human_input=True, **values)
        validate_annotation(
            annotation,
            set(taxonomy.intent_ids),
            set(config["actions"]),
            set(config["difficulties"]),
            set(config["risk_tags"]),
        )
        store.save(annotation, explicit_human_input=True)
        count += 1
        print("Saved atomically.")
    completed, total, next_case = store.progress(candidates)
    print(f"Progress: {completed}/{total}; next={next_case}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
