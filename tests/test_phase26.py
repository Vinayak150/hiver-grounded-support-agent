from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from support_agent.annotation.provisional import confirm_provisional_as_human
from support_agent.annotation.schema import AIProvisionalLabel, FrozenCandidate
from support_agent.annotation.store import (
    AnnotationStore,
    golden_set_status,
    load_ai_provisional_labels,
    load_frozen_candidates,
)
from support_agent.data.protection import assert_no_frozen_thread_ids

ROOT = Path(__file__).resolve().parents[1]


def _case(case_id: str, thread_id: str) -> FrozenCandidate:
    return FrozenCandidate(
        case_id=case_id,
        thread_id=thread_id,
        customer_message="Playback is broken",
        conversation_context="CUSTOMER: Playback is broken",
        candidate_type="REPRESENTATIVE",
        timestamp="2017-12-01T00:00:00+00:00",
        taxonomy_version="spotify-intents-v1",
        split_version="spotify-temporal-v1",
        sampling_version="spotify-golden-candidates-v1",
    )


def _label(case_id: str, intent: str = "playback_or_app_behavior") -> AIProvisionalLabel:
    return AIProvisionalLabel(
        case_id=case_id,
        suggested_intent=intent,
        intent_confidence="0.80",
        suggested_action="AUTO_HANDLE",
        action_confidence="0.78",
        suggested_risk_tags="",
        short_reason="Public guidance appears sufficient.",
        uncertainty_flags="",
        model_name="test-model",
        prompt_version="test-v1",
    )


def test_committed_frozen_set_has_exact_contract_and_protected_membership() -> None:
    cases = load_frozen_candidates(ROOT / "data/annotations/final_golden_candidates.csv")
    manifest = json.loads(
        (ROOT / "data/manifests/final_golden_candidate_manifest.json").read_text()
    )
    splits = json.loads((ROOT / "data/manifests/split_manifest.json").read_text())
    counts = Counter(case.candidate_type for case in cases)
    thread_ids = {case.thread_id for case in cases}
    assert len(cases) == len(thread_ids) == 200
    assert counts == {"REPRESENTATIVE": 160, "CHALLENGE": 40}
    assert thread_ids == set(manifest["thread_ids"])
    assert thread_ids <= set(splits["thread_ids"]["GOLDEN_CANDIDATE"])
    assert not thread_ids & set(splits["thread_ids"]["TRAIN"])
    assert not thread_ids & set(splits["thread_ids"]["DEVELOPMENT"])
    assert manifest["selection_evidence"]["internal_exact_duplicates"] == 0
    assert manifest["selection_evidence"]["internal_near_duplicates"] == 0
    leakage = json.loads((ROOT / "data/manifests/leakage_audit.json").read_text())
    assert leakage["protected_boundaries_clean"] is True


def test_committed_provisional_labels_are_separate_and_ai_only() -> None:
    cases = load_frozen_candidates(ROOT / "data/annotations/final_golden_candidates.csv")
    labels = load_ai_provisional_labels(ROOT / "data/annotations/ai_provisional_labels.csv")
    assert set(labels) == {case.case_id for case in cases}
    assert len(labels) == 200
    assert {label.annotation_source for label in labels.values()} == {"AI_PROVISIONAL"}
    with (ROOT / "data/annotations/golden_annotations.csv").open(newline="") as stream:
        human_rows = list(csv.DictReader(stream))
    assert all(row["annotation_source"] == "human" for row in human_rows)


def test_ai_suggestion_cannot_become_human_gold_without_confirmation() -> None:
    case = _case("case-1", "thread-1")
    label = _label(case.case_id)
    with pytest.raises(ValueError, match="explicit human confirmation"):
        confirm_provisional_as_human(
            case,
            label,
            explicit_confirmation=False,
            difficulty="EASY",
        )
    annotation = confirm_provisional_as_human(
        case,
        label,
        explicit_confirmation=True,
        difficulty="EASY",
    )
    assert annotation.annotation_source == "human"
    assert annotation.gold_intent == label.suggested_intent


def test_unsure_suggestion_must_be_corrected() -> None:
    case = _case("case-1", "thread-1")
    with pytest.raises(ValueError, match="corrected"):
        confirm_provisional_as_human(
            case,
            _label(case.case_id, intent="UNSURE"),
            explicit_confirmation=True,
            difficulty="HARD",
        )


def test_review_progress_resumes_within_frozen_queue(tmp_path: Path) -> None:
    first = _case("case-1", "thread-1")
    second = _case("case-2", "thread-2")
    unrelated = _case("case-other", "thread-other")
    store = AnnotationStore(tmp_path / "annotations.csv")
    store.initialize()
    store.save(
        confirm_provisional_as_human(
            first, _label(first.case_id), explicit_confirmation=True, difficulty="EASY"
        ),
        explicit_human_input=True,
    )
    store.save(
        confirm_provisional_as_human(
            unrelated,
            _label(unrelated.case_id),
            explicit_confirmation=True,
            difficulty="EASY",
        ),
        explicit_human_input=True,
    )
    assert store.progress([first, second]) == (1, 2, "case-2")
    assert golden_set_status(149) == "AWAITING_HUMAN_CONFIRMATION"
    assert golden_set_status(150) == "READY_FOR_FINAL_EVALUATION"


def test_train_and_development_workflows_reject_frozen_ids(tmp_path: Path) -> None:
    manifest = tmp_path / "frozen.json"
    manifest.write_text(json.dumps({"thread_ids": ["gold-1", "gold-2"]}), encoding="utf-8")
    assert_no_frozen_thread_ids({"train-1", "dev-1"}, manifest, "training")
    with pytest.raises(ValueError, match="frozen evaluation"):
        assert_no_frozen_thread_ids({"train-1", "gold-2"}, manifest, "training")
