from __future__ import annotations

import csv
from pathlib import Path

import pytest

from support_agent.annotation.queue import sample_candidates
from support_agent.annotation.schema import (
    ANNOTATION_FIELDS,
    CandidateCase,
    build_human_annotation,
    validate_annotation,
)
from support_agent.annotation.store import AnnotationStore
from support_agent.data.spotify import SupportThread, Turn
from support_agent.taxonomy.schema import validate_taxonomy


def _thread(thread_id: str, text: str) -> SupportThread:
    timestamp = f"2017-01-{int(thread_id[-1]) + 1:02d}T00:00:00Z"
    turns = (
        Turn(f"{thread_id}-1", "CUSTOMER", text, timestamp, None),
        Turn(f"{thread_id}-2", "SPOTIFY", "Try restarting the app.", timestamp, f"{thread_id}-1"),
    )
    return SupportThread(thread_id, f"root-{thread_id}", 2, 1, 1, timestamp, timestamp, 2, turns)


def _taxonomy():
    return validate_taxonomy(
        {
            "version": "v1",
            "brand": "SpotifyCares",
            "source_split": "TRAIN",
            "default_intent": "other",
            "intents": [
                {
                    "id": "playback",
                    "display_name": "Playback",
                    "definition": "Playback problems",
                    "include_when": "Playback is central",
                    "exclude_when": "No playback problem",
                    "boundary_notes": "Prefer specific support intent",
                    "common_signals": ["play"],
                },
                {
                    "id": "other",
                    "display_name": "Other",
                    "definition": "Unclear",
                    "include_when": "No intent is clear",
                    "exclude_when": "A specific intent is clear",
                    "boundary_notes": "Preserve abstention",
                    "common_signals": [],
                },
            ],
        }
    )


def _case() -> CandidateCase:
    return CandidateCase(
        "case-1", "gold0", "v1", "sample-v1", "split-v1", "CHALLENGE", "help", "", "VERY_SHORT"
    )


def _annotation(case: CandidateCase, **overrides: str):
    values = {
        "gold_intent": "playback",
        "gold_action": "AUTO_HANDLE",
        "gold_action_reason": "Public troubleshooting is sufficient.",
        "difficulty": "EASY",
        "risk_tags": "",
        "annotation_notes": "",
    }
    values.update(overrides)
    return build_human_annotation(case, explicit_human_input=True, **values)


def test_candidate_sampling_is_deterministic_and_uses_only_supplied_golden_threads() -> None:
    train = [_thread("train0", "songs will not play")]
    golden = [_thread(f"gold{index}", f"song play issue number {index}") for index in range(1, 6)]
    config = {
        "candidate_count": 3,
        "representative_count": 2,
        "challenge_count": 1,
        "seed": "seed",
        "taxonomy_version": "v1",
        "sampling_version": "sample-v1",
        "split_version": "split-v1",
    }
    first = sample_candidates(golden, train, _taxonomy(), config)
    second = sample_candidates(list(reversed(golden)), train, _taxonomy(), config)
    assert first == second
    assert {row.thread_id for row in first} <= {thread.thread_id for thread in golden}
    assert "train0" not in {row.thread_id for row in first}


def test_annotation_store_resumes_and_prevents_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "annotations.csv"
    store = AnnotationStore(path)
    store.initialize()
    case = _case()
    store.save(_annotation(case), explicit_human_input=True)
    assert store.progress([case]) == (1, 1, None)
    with pytest.raises(ValueError, match="already annotated"):
        store.save(_annotation(case), explicit_human_input=True)


def test_invalid_intent_and_action_are_rejected() -> None:
    case = _case()
    validation = ({"playback", "other"}, {"AUTO_HANDLE", "ESCALATE"}, {"EASY"}, set())
    with pytest.raises(ValueError, match="intent"):
        validate_annotation(_annotation(case, gold_intent="invented"), *validation)
    with pytest.raises(ValueError, match="action"):
        validate_annotation(_annotation(case, gold_action="MAYBE"), *validation)


def test_human_row_requires_explicit_input_and_store_rechecks_it(tmp_path: Path) -> None:
    case = _case()
    with pytest.raises(ValueError, match="explicit"):
        build_human_annotation(case, explicit_human_input=False, gold_intent="playback")
    with pytest.raises(ValueError, match="explicit"):
        AnnotationStore(tmp_path / "annotations.csv").save(
            _annotation(case), explicit_human_input=False
        )


def test_empty_annotation_file_contains_header_only(tmp_path: Path) -> None:
    path = tmp_path / "annotations.csv"
    AnnotationStore(path).initialize()
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows == [list(ANNOTATION_FIELDS)]
