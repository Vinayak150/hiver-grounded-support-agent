#!/usr/bin/env python3
"""Blind, keyboard-only, resumable CLI for explicit human gold annotation."""

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
from support_agent.annotation.store import (  # noqa: E402
    AnnotationStore,
    golden_set_status,
    load_ai_provisional_labels,
    load_candidates,
    load_frozen_candidates,
)
from support_agent.taxonomy.schema import Taxonomy, load_taxonomy  # noqa: E402


def _customer_context(case) -> str:
    messages = []
    for part in case.conversation_context.split(" || "):
        role, separator, text = part.partition(":")
        if separator and role.strip() == "CUSTOMER":
            normalized = text.strip()
            if normalized and normalized != case.customer_message and normalized not in messages:
                messages.append(normalized)
    return "\n".join(f"- {message}" for message in messages) or "(none beyond the message above)"


def _print_taxonomy(taxonomy: Taxonomy) -> None:
    print("\nINTENT SHORTCUTS")
    for number, intent in enumerate(taxonomy.intents, start=1):
        print(f"  {number}  {intent.id}: {intent.definition}")
    print("\nACTION: a=AUTO_HANDLE, e=ESCALATE")
    print("DIFFICULTY: 1=EASY, 2=MEDIUM, 3=HARD")
    print("At the intent prompt: p=correct previous saved case, q=save progress and quit")


def _prompt_choice(prompt: str, mapping: dict[str, str]) -> str:
    while True:
        value = input(prompt).strip().casefold()
        if value in mapping:
            return mapping[value]
        print("Invalid shortcut. Choose: " + ", ".join(mapping))


def _prompt_risk_tags(config: dict[str, object]) -> str:
    tags = tuple(str(value) for value in config["risk_tags"])
    print("RISK TAGS (optional, comma-separated numbers; Enter for none)")
    print("  " + " | ".join(f"{index}={tag}" for index, tag in enumerate(tags, start=1)))
    while True:
        raw = input("Risk tags> ").strip()
        if not raw:
            return ""
        try:
            selected = [tags[int(value.strip()) - 1] for value in raw.split(",")]
        except (ValueError, IndexError):
            print("Invalid risk-tag shortcut.")
            continue
        return "|".join(dict.fromkeys(selected))


def _display_case(case, position: int, total: int, completed: int) -> None:
    print("\n" + "=" * 78)
    print(f"[{position}/{total}]  completed={completed}  remaining={total - completed}")
    print(f"CASE: {case.case_id}")
    print("\nCUSTOMER")
    print(case.customer_message)
    print("\nADDITIONAL CUSTOMER CONTEXT")
    print(_customer_context(case))


def _collect_annotation(case, taxonomy: Taxonomy, config: dict[str, object]):
    intent_map = {
        str(index): intent.id for index, intent in enumerate(taxonomy.intents, start=1)
    }
    shortcuts = "  ".join(f"{key}={value}" for key, value in intent_map.items())
    print("\nINTENT")
    print(shortcuts)
    intent_command = input("Intent [1-9, p previous, q quit]> ").strip().casefold()
    if intent_command in {"p", "q"}:
        return intent_command
    while intent_command not in intent_map:
        print("Invalid intent shortcut.")
        intent_command = input("Intent [1-9, p previous, q quit]> ").strip().casefold()
        if intent_command in {"p", "q"}:
            return intent_command
    action = _prompt_choice("Action [a/e]> ", {"a": "AUTO_HANDLE", "e": "ESCALATE"})
    difficulty = _prompt_choice(
        "Difficulty [1/2/3]> ", {"1": "EASY", "2": "MEDIUM", "3": "HARD"}
    )
    risk_tags = _prompt_risk_tags(config)
    reason = ""
    while not reason:
        reason = input("Short reason for the action> ").strip()
        if not reason:
            print("A short human-written action reason is required.")
    return build_human_annotation(
        case,
        explicit_human_input=True,
        annotator="candidate",
        gold_intent=intent_map[intent_command],
        gold_action=action,
        difficulty=difficulty,
        risk_tags=risk_tags,
        gold_action_reason=reason,
        annotation_notes="",
    )


def _validate(annotation, taxonomy: Taxonomy, config: dict[str, object]) -> None:
    validate_annotation(
        annotation,
        set(taxonomy.intent_ids),
        set(config["actions"]),
        set(config["difficulties"]),
        set(config["risk_tags"]),
    )


def _post_save_comparison(annotation, suggestion) -> None:
    if suggestion is None:
        return
    intent_status = (
        "MATCH" if annotation.gold_intent == suggestion.suggested_intent else "DIFFERENT"
    )
    action_status = (
        "MATCH" if annotation.gold_action == suggestion.suggested_action else "DIFFERENT"
    )
    print(
        "POST-SAVE AI COMPARISON (diagnostic only; decision already locked): "
        f"intent={intent_status}, action={action_status}"
    )


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
    parser.add_argument(
        "--human-gold",
        action="store_true",
        help="Blindly review the frozen 200 cases without showing provisional choices.",
    )
    parser.add_argument(
        "--review-provisional",
        action="store_true",
        help="Deprecated alias for --human-gold; suggestions are now hidden until save.",
    )
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
    frozen_mode = arguments.human_gold or arguments.review_provisional
    candidates = (
        load_frozen_candidates(arguments.frozen_candidates)
        if frozen_mode
        else load_candidates(arguments.candidates)
    )
    provisional = (
        load_ai_provisional_labels(arguments.provisional_labels) if frozen_mode else {}
    )
    if frozen_mode and set(provisional) != {case.case_id for case in candidates}:
        raise ValueError("Human-gold mode requires one separate provisional row per frozen case.")
    taxonomy = load_taxonomy(arguments.taxonomy)
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    store = AnnotationStore(arguments.output)
    store.initialize()
    completed, total, next_case = store.progress(candidates)
    if arguments.progress:
        print(f"Progress: {completed}/{total}; remaining={total - completed}; next={next_case}")
        print(f"GOLDEN_SET_STATUS: {golden_set_status(completed)}")
        return 0

    _print_taxonomy(taxonomy)
    saved_this_session = 0
    while True:
        existing = store.load()
        next_index = next(
            (index for index, case in enumerate(candidates) if case.case_id not in existing),
            None,
        )
        if next_index is None:
            break
        if arguments.limit is not None and saved_this_session >= arguments.limit:
            break
        case = candidates[next_index]
        _display_case(case, next_index + 1, total, len(existing))
        result = _collect_annotation(case, taxonomy, config)
        if result == "q":
            break
        if result == "p":
            previous = next(
                (
                    candidate
                    for candidate in reversed(candidates[:next_index])
                    if candidate.case_id in existing
                ),
                None,
            )
            if previous is None:
                print("No previous saved case is available to correct.")
                continue
            previous_index = candidates.index(previous)
            _display_case(previous, previous_index + 1, total, len(existing))
            corrected = _collect_annotation(previous, taxonomy, config)
            if corrected in {"p", "q"}:
                print("Correction cancelled; existing row was preserved.")
                if corrected == "q":
                    break
                continue
            _validate(corrected, taxonomy, config)
            store.replace(corrected, explicit_human_input=True)
            print("Previous case corrected and saved atomically.")
            _post_save_comparison(corrected, provisional.get(previous.case_id))
            continue
        _validate(result, taxonomy, config)
        store.save(result, explicit_human_input=True)
        saved_this_session += 1
        print("Saved atomically.")
        _post_save_comparison(result, provisional.get(case.case_id))

    completed, total, next_case = store.progress(candidates)
    print(f"Progress: {completed}/{total}; remaining={total - completed}; next={next_case}")
    print(f"GOLDEN_SET_STATUS: {golden_set_status(completed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
