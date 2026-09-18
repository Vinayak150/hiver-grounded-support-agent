#!/usr/bin/env python3
"""Blinded, resumable CLI for explicit human golden-set annotation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.provisional import confirm_provisional_as_human  # noqa: E402
from support_agent.annotation.schema import (  # noqa: E402
    build_human_annotation,
    validate_annotation,
)
from support_agent.annotation.store import (  # noqa: E402
    AnnotationStore,
    golden_set_status,
    load_ai_provisional_labels,
    load_candidates,
    load_frozen_candidates,
)
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
    parser.add_argument("--review-provisional", action="store_true")
    parser.add_argument(
        "--frozen-candidates",
        type=Path,
        default=Path("data/annotations/final_golden_candidates.csv"),
    )
    parser.add_argument(
        "--provisional-labels",
        type=Path,
        default=Path("data/annotations/ai_provisional_labels.csv"),
    )
    arguments = parser.parse_args()
    candidates = (
        load_frozen_candidates(arguments.frozen_candidates)
        if arguments.review_provisional
        else load_candidates(arguments.candidates)
    )
    provisional = (
        load_ai_provisional_labels(arguments.provisional_labels)
        if arguments.review_provisional
        else {}
    )
    if arguments.review_provisional and set(provisional) != {case.case_id for case in candidates}:
        raise ValueError("Review mode requires one AI provisional row per frozen case.")
    taxonomy = load_taxonomy(arguments.taxonomy)
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    store = AnnotationStore(arguments.output)
    store.initialize()
    completed, total, next_case = store.progress(candidates)
    if arguments.progress:
        print(f"Progress: {completed}/{total}; next={next_case}")
        print(f"GOLDEN_SET_STATUS: {golden_set_status(completed)}")
        return 0
    presented = 0
    saved = 0
    completed_ids = set(store.load())
    for case in candidates:
        if case.case_id in completed_ids:
            continue
        if arguments.limit is not None and presented >= arguments.limit:
            break
        presented += 1
        print(f"\n[{case.case_id}] {completed + saved + 1}/{total}")
        print(case.customer_message)
        print(f"Context: {case.conversation_context}")
        suggestion = provisional.get(case.case_id)
        if suggestion is not None:
            print("\nAI PROVISIONAL SUGGESTION (not gold; never auto-accepted)")
            print(f"Intent: {suggestion.suggested_intent} ({suggestion.intent_confidence})")
            print(f"Action: {suggestion.suggested_action} ({suggestion.action_confidence})")
            print(f"Risk tags: {suggestion.suggested_risk_tags or '(none)'}")
            print(f"Reason: {suggestion.short_reason}")
            print(f"Uncertainty: {suggestion.uncertainty_flags or '(none)'}")
            command = input("Accept [a], correct [c], defer [d], or quit [q]: ").strip().casefold()
        else:
            command = input("Annotate [a], defer [d], or quit [q]: ").strip().casefold()
        if command == "q":
            break
        if command == "d":
            continue
        if suggestion is not None and command == "a":
            if "UNSURE" in {suggestion.suggested_intent, suggestion.suggested_action}:
                print("UNSURE suggestions must be corrected; case not saved.")
                continue
            confirmation = input(
                "Type CONFIRM to adopt this suggestion as your human decision: "
            ).strip()
            if confirmation != "CONFIRM":
                print("Confirmation not supplied; case not saved.")
                continue
            difficulty = _choose("Difficulty: ", tuple(config["difficulties"]))
            notes = input("Optional human notes: ").strip()
            annotation = confirm_provisional_as_human(
                case,
                suggestion,
                explicit_confirmation=True,
                difficulty=difficulty,
                annotation_notes=notes,
            )
        elif command in ({"a"} if suggestion is None else {"c"}):
            values = {
                "gold_intent": _choose("Intent: ", taxonomy.intent_ids),
                "gold_action": _choose("Action: ", tuple(config["actions"])),
                "difficulty": _choose("Difficulty: ", tuple(config["difficulties"])),
                "risk_tags": input("Risk tags separated by | (blank allowed): ").strip(),
                "gold_action_reason": input("Short action reason: ").strip(),
                "annotation_notes": input("Optional notes: ").strip(),
            }
            annotation = build_human_annotation(case, explicit_human_input=True, **values)
        else:
            print("Unknown command; case not saved.")
            continue
        validate_annotation(
            annotation,
            set(taxonomy.intent_ids),
            set(config["actions"]),
            set(config["difficulties"]),
            set(config["risk_tags"]),
        )
        store.save(annotation, explicit_human_input=True)
        completed_ids.add(case.case_id)
        saved += 1
        print("Saved atomically.")
    completed, total, next_case = store.progress(candidates)
    print(f"Progress: {completed}/{total}; next={next_case}")
    print(f"GOLDEN_SET_STATUS: {golden_set_status(completed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
