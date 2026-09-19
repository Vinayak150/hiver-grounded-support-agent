from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

import scripts.review_response_quality as review_module
from scripts.review_response_quality import (
    RESPONSE_QUALITY_FIELDS,
    ResponseQualityAnnotation,
    ResponseQualityStore,
    build_review_plan,
    normalize_decision,
    run_review,
)
from scripts.run_final_evaluation import _load_response_quality
from support_agent.annotation.schema import FrozenCandidate, HumanAnnotation


def _candidate(case_id: str, number: int) -> FrozenCandidate:
    return FrozenCandidate(
        case_id=case_id,
        thread_id=f"thread-{number}",
        customer_message=f"Customer question {number}",
        conversation_context=(
            f"CUSTOMER: Customer question {number} || "
            f"SPOTIFY: Old answer {number} || CUSTOMER: More context {number}"
        ),
        candidate_type="REPRESENTATIVE",
        timestamp="2017-01-01T00:00:00+00:00",
        taxonomy_version="taxonomy-v1",
        split_version="split-v1",
        sampling_version="sampling-v1",
    )


def _gold(candidate: FrozenCandidate) -> HumanAnnotation:
    return HumanAnnotation(
        case_id=candidate.case_id,
        thread_id=candidate.thread_id,
        taxonomy_version=candidate.taxonomy_version,
        sampling_version=candidate.sampling_version,
        split_version=candidate.split_version,
        gold_intent="intent-a",
        gold_action="AUTO_HANDLE",
        gold_action_reason="Human gold reason.",
        difficulty="EASY",
        risk_tags="",
        annotation_notes="",
        annotator="candidate",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )


def _prediction(case_id: str, action: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "intent": "intent-a",
        "action": action,
        "action_reason": "Deterministic gates passed." if action == "AUTO_HANDLE" else "Escalate.",
        "reply": "Please try the documented troubleshooting steps.",
        "evidence_ids": [f"evidence-{case_id}"] if action == "AUTO_HANDLE" else [],
    }


def _detail(case_id: str, action: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "action": action,
        "retrieved_cases": [
            {
                "thread_id": f"evidence-{case_id}",
                "intent": "intent-a",
                "historical_reply": "A prior public support answer.",
                "judge_score": "DO_NOT_DISPLAY_SENTINEL",
            }
        ],
        "evidence_sufficient": action == "AUTO_HANDLE",
        "grounding_passed": action == "AUTO_HANDLE",
        "risk_tags": [],
        "reason_codes": [],
        "provisional_ai_judgment": "DO_NOT_DISPLAY_SENTINEL",
    }


@pytest.fixture
def review_fixture():
    candidates = [_candidate("case-1", 1), _candidate("case-2", 2), _candidate("case-3", 3)]
    gold = {candidate.case_id: _gold(candidate) for candidate in candidates}
    predictions = [
        _prediction("case-1", "AUTO_HANDLE"),
        _prediction("case-2", "ESCALATE"),
        _prediction("case-3", "AUTO_HANDLE"),
    ]
    details = [
        _detail("case-1", "AUTO_HANDLE"),
        _detail("case-2", "ESCALATE"),
        _detail("case-3", "AUTO_HANDLE"),
    ]
    return candidates, gold, predictions, details


def _inputs(monkeypatch: pytest.MonkeyPatch, values: list[str]) -> None:
    entered = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(entered))


def test_plan_includes_only_final_proposed_auto_handle_cases(review_fixture) -> None:
    candidates, gold, predictions, details = review_fixture
    plan = build_review_plan(candidates, gold, predictions, details)
    assert [item.candidate.case_id for item in plan] == ["case-1", "case-3"]
    assert all(item.prediction["action"] == "AUTO_HANDLE" for item in plan)


def test_required_csv_schema_is_exact_and_ordered() -> None:
    assert RESPONSE_QUALITY_FIELDS == (
        "case_id",
        "response_quality_approved",
        "reason",
        "annotation_source",
        "status",
    )


def test_review_resume_atomic_schema_normalization_and_final_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    review_fixture,
) -> None:
    candidates, gold, predictions, details = review_fixture
    plan = build_review_plan(candidates, gold, predictions, details)
    output = tmp_path / "human_response_quality.csv"
    store = ResponseQualityStore(output)

    replace_calls: list[tuple[object, object]] = []
    real_replace = os.replace

    def record_replace(source, destination) -> None:
        replace_calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(review_module.os, "replace", record_replace)
    _inputs(monkeypatch, [" Y ", "Safe, grounded answer.", "q"])
    run_review(plan, store)
    first_output = capsys.readouterr().out
    assert "RESPONSE_QUALITY_STATUS=INCOMPLETE" in first_output
    assert set(store.load()) == {"case-1"}
    assert len(replace_calls) == 2  # Header initialization and the first completed judgment.
    assert not list(tmp_path.glob(".human_response_quality.csv.*"))

    with output.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames or ()) == RESPONSE_QUALITY_FIELDS

    _inputs(monkeypatch, ["n", "Not complete enough for automatic sending."])
    run_review(plan, store)
    second_output = capsys.readouterr().out
    assert "CASE ID: case-1" not in second_output
    assert "CASE ID: case-3" in second_output
    assert "RESPONSE_QUALITY_REVIEWED=2" in second_output
    assert "REQUIRED_AUTO_HANDLE=2" in second_output
    assert "REMAINING=0" in second_output
    assert "RESPONSE_QUALITY_STATUS=READY" in second_output

    rows = store.load()
    assert set(rows) == {"case-1", "case-3"}
    assert rows["case-1"].response_quality_approved == "true"
    assert rows["case-3"].response_quality_approved == "false"
    assert all(row.annotation_source == "human" for row in rows.values())
    assert all(row.status == "FINALIZED" for row in rows.values())
    assert _load_response_quality(output, {"case-1", "case-3"}) == {
        "case-1": True,
        "case-3": False,
    }


def test_reviewer_does_not_show_ai_or_provisional_judgments_before_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    review_fixture,
) -> None:
    candidates, gold, predictions, details = review_fixture
    plan = build_review_plan(candidates, gold, predictions, details)
    _inputs(monkeypatch, ["q"])
    run_review(plan, ResponseQualityStore(tmp_path / "quality.csv"))
    displayed = capsys.readouterr().out
    assert "DO_NOT_DISPLAY_SENTINEL" not in displayed
    assert "judge_score" not in displayed.casefold()
    assert "provisional" not in displayed.casefold()


def test_duplicate_case_ids_are_rejected(tmp_path: Path, review_fixture) -> None:
    candidates, gold, predictions, details = review_fixture
    with pytest.raises(ValueError, match="duplicate case IDs"):
        build_review_plan(candidates, gold, predictions + [predictions[0]], details)

    output = tmp_path / "duplicate.csv"
    output.write_text(
        ",".join(RESPONSE_QUALITY_FIELDS)
        + "\ncase-1,true,First,human,FINALIZED\n"
        + "case-1,false,Second,human,FINALIZED\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate case IDs"):
        ResponseQualityStore(output).load()


def test_store_rejects_escalate_rows_and_requires_explicit_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_fixture,
) -> None:
    candidates, gold, predictions, details = review_fixture
    plan = build_review_plan(candidates, gold, predictions, details)
    store = ResponseQualityStore(tmp_path / "quality.csv")
    store.initialize()
    store.save(ResponseQualityAnnotation("case-2", "true", "Should not be present."))
    with pytest.raises(ValueError, match="non-AUTO_HANDLE"):
        run_review(plan, store)

    clean_store = ResponseQualityStore(tmp_path / "clean.csv")
    clean_store.initialize()
    clean_store.save(ResponseQualityAnnotation("case-1", "true", "Original reason."))
    with pytest.raises(ValueError, match="already has a finalized judgment"):
        clean_store.save(ResponseQualityAnnotation("case-1", "false", "Replacement."))
    _inputs(monkeypatch, ["n", "Explicitly revised by the human reviewer."])
    run_review(plan, clean_store, revise_case_id="case-1")
    assert clean_store.load()["case-1"].response_quality_approved == "false"


@pytest.mark.parametrize(
    ("raw", "expected"), [("y", True), (" Y ", True), ("n", False), ("N", False)]
)
def test_y_n_normalization(raw: str, expected: bool) -> None:
    assert normalize_decision(raw) is expected


def test_invalid_decision_is_rejected() -> None:
    with pytest.raises(ValueError, match="y or n"):
        normalize_decision("yes")
