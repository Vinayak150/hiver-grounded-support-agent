from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

import scripts.review_human_judge as review_module
from scripts.review_human_judge import (
    HUMAN_RATING_FIELDS,
    NOTES_FIELDS,
    SAMPLE_PROTOCOL,
    SAMPLE_SIZE,
    HumanJudgeNote,
    HumanJudgeRating,
    HumanJudgeStore,
    HumanReviewItem,
    deterministic_sample,
    load_or_create_sample_manifest,
    load_review_items,
    overall_pass_from_scores,
    run_review,
)

ROOT = Path(__file__).resolve().parents[1]


def _primary_rows() -> list[dict[str, object]]:
    return [
        {
            "case_id": f"case-{number:03d}",
            "system": system,
            "run_id": "primary",
            "groundedness": (number % 5) + 1,
            "overall_pass": number % 2 == 0,
            "critical_failure": False,
            "failure_codes": ["G"],
            "rationale": f"hidden rationale {number}",
        }
        for system in ("proposed", "lexical", "fixed")
        for number in range(80)
    ]


def _items() -> list[HumanReviewItem]:
    systems = ("proposed", "lexical", "fixed")
    return [
        HumanReviewItem(
            case_id=f"case-{index:03d}",
            system=systems[index % len(systems)],
            customer=f"Customer text {index}",
            additional_context=f"Additional context {index}",
            action="AUTO_HANDLE" if index % 2 == 0 else "ESCALATE",
            reply=f"Anonymous candidate reply {index}",
            evidence=((f"evidence-{index}", f"Historical excerpt {index}"),),
        )
        for index in range(SAMPLE_SIZE)
    ]


def _inputs(monkeypatch: pytest.MonkeyPatch, values: list[str]) -> None:
    entered = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(entered))


def _rating(case_id: str, system: str, score: str = "4") -> HumanJudgeRating:
    return HumanJudgeRating(
        case_id=case_id,
        system=system,
        groundedness=score,
        relevance=score,
        helpfulness=score,
        safety=score,
        brand_context=score,
        overall_pass="true" if score in {"4", "5"} else "false",
    )


def _note(case_id: str, system: str, critical: str = "false") -> HumanJudgeNote:
    return HumanJudgeNote(case_id, system, critical, "Synthetic test note.")


def test_deterministic_sample_is_40_and_balanced() -> None:
    first = deterministic_sample(_primary_rows())
    second = deterministic_sample(list(reversed(_primary_rows())))
    assert first == second
    assert len(first) == SAMPLE_SIZE == 40
    assert len({(row["case_id"], row["system"]) for row in first}) == 40
    assert Counter(row["system"] for row in first) == {
        "proposed": 14,
        "lexical": 13,
        "fixed": 13,
    }


def test_sample_selection_is_independent_of_every_llm_judgment_field() -> None:
    original = _primary_rows()
    changed = []
    for row in original:
        changed.append(
            {
                **row,
                "groundedness": 99,
                "relevance": -1,
                "helpfulness": "changed",
                "safety": None,
                "brand_context": {},
                "overall_pass": not bool(row["overall_pass"]),
                "critical_failure": True,
                "failure_codes": ["P", "F"],
                "rationale": "completely changed",
            }
        )
    assert deterministic_sample(original) == deterministic_sample(changed)


def test_existing_manifest_is_reused_without_resampling(tmp_path: Path) -> None:
    selected = deterministic_sample(_primary_rows())
    manifest = {
        "protocol": SAMPLE_PROTOCOL,
        "rubric_version": "support-response-rubric-v1",
        "sample_size": SAMPLE_SIZE,
        "selected_keys": selected,
        "status": "FROZEN_BEFORE_HUMAN_RATINGS",
        "system_counts": {"fixed": 13, "lexical": 13, "proposed": 14},
    }
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    before = path.read_bytes()
    loaded = load_or_create_sample_manifest(
        path,
        tmp_path / "missing-source.json",
        [],
        tmp_path / "missing-results.jsonl",
    )
    assert loaded == manifest
    assert path.read_bytes() == before


def test_exact_csv_schemas_and_human_finalized_provenance(tmp_path: Path) -> None:
    assert HUMAN_RATING_FIELDS == (
        "case_id",
        "system",
        "groundedness",
        "relevance",
        "helpfulness",
        "safety",
        "brand_context",
        "overall_pass",
        "annotation_source",
        "status",
    )
    assert NOTES_FIELDS == ("case_id", "system", "critical_failure", "note")
    store = HumanJudgeStore(tmp_path / "ratings.csv", tmp_path / "notes.csv")
    store.initialize()
    allowed = {("case-001", "proposed")}
    store.save(_rating(*next(iter(allowed))), _note(*next(iter(allowed))), allowed)
    with store.ratings_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == HUMAN_RATING_FIELDS
    assert rows[0]["annotation_source"] == "human"
    assert rows[0]["status"] == "FINALIZED"


@pytest.mark.parametrize(
    ("scores", "critical", "expected"),
    [
        (
            {"groundedness": 4, "relevance": 3, "helpfulness": 3, "safety": 4, "brand_context": 3},
            False,
            True,
        ),
        (
            {"groundedness": 3, "relevance": 5, "helpfulness": 5, "safety": 5, "brand_context": 5},
            False,
            False,
        ),
        (
            {"groundedness": 5, "relevance": 5, "helpfulness": 5, "safety": 3, "brand_context": 5},
            False,
            False,
        ),
        (
            {"groundedness": 5, "relevance": 2, "helpfulness": 5, "safety": 5, "brand_context": 5},
            False,
            False,
        ),
        (
            {"groundedness": 5, "relevance": 5, "helpfulness": 5, "safety": 5, "brand_context": 5},
            True,
            False,
        ),
    ],
)
def test_exact_overall_pass_derivation(
    scores: dict[str, int], critical: bool, expected: bool
) -> None:
    assert overall_pass_from_scores(scores, critical) is expected


def test_score_validation_rejects_values_outside_one_to_five(tmp_path: Path) -> None:
    store = HumanJudgeStore(tmp_path / "ratings.csv", tmp_path / "notes.csv")
    store.initialize()
    key = ("case-001", "proposed")
    with pytest.raises(ValueError, match="one through five"):
        store.save(_rating(*key, score="6"), _note(*key), {key})


def test_duplicate_case_system_rows_are_rejected(tmp_path: Path) -> None:
    ratings = tmp_path / "ratings.csv"
    ratings.write_text(
        ",".join(HUMAN_RATING_FIELDS)
        + "\ncase-1,proposed,4,4,4,4,4,true,human,FINALIZED"
        + "\ncase-1,proposed,4,4,4,4,4,true,human,FINALIZED\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate case/system"):
        HumanJudgeStore(ratings, tmp_path / "notes.csv").load_ratings()


def test_resume_atomic_persistence_q_and_blind_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    items = _items()
    store = HumanJudgeStore(tmp_path / "ratings.csv", tmp_path / "notes.csv")
    replace_calls: list[tuple[object, object]] = []
    real_replace = os.replace

    def record_replace(source, destination) -> None:
        replace_calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(review_module.os, "replace", record_replace)
    _inputs(monkeypatch, ["4", "4", "4", "4", "4", "n", "Good response.", "q"])
    run_review(items, store)
    first_output = capsys.readouterr().out
    assert "PROGRESS 1/40" in first_output
    assert "HUMAN_JUDGE_REVIEWED=1" in first_output
    assert "HUMAN_JUDGE_REVIEW_STATUS=INCOMPLETE" in first_output
    assert "proposed" not in first_output.casefold()
    assert "lexical" not in first_output.casefold()
    assert "fixed" not in first_output.casefold()
    assert len(store.load_ratings()) == 1
    assert len(replace_calls) == 4  # Two atomic files at initialization and save.
    assert not list(tmp_path.glob(".*.csv.*"))

    _inputs(monkeypatch, ["3", "3", "3", "4", "3", "n", "Limited but safe.", "q"])
    run_review(items, store)
    second_output = capsys.readouterr().out
    assert "PROGRESS 1/40" not in second_output
    assert "PROGRESS 2/40" in second_output
    assert len(store.load_ratings()) == 2


def test_blind_display_cannot_leak_llm_judgment_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    items = _items()
    sentinel_fields = {
        "groundedness": 1,
        "relevance": 2,
        "helpfulness": 3,
        "safety": 4,
        "brand_context": 5,
        "overall_pass": False,
        "critical_failure": True,
        "failure_codes": ["DO_NOT_DISPLAY_CODE"],
        "rationale": "DO_NOT_DISPLAY_RATIONALE",
    }
    assert sentinel_fields  # The human item type has nowhere to carry these fields.
    _inputs(monkeypatch, ["q"])
    run_review(
        items,
        HumanJudgeStore(tmp_path / "ratings.csv", tmp_path / "notes.csv"),
    )
    output = capsys.readouterr().out
    assert "DO_NOT_DISPLAY_CODE" not in output
    assert "DO_NOT_DISPLAY_RATIONALE" not in output
    assert "CANDIDATE REPLY" in output


def test_only_frozen_sample_keys_can_be_saved(tmp_path: Path) -> None:
    store = HumanJudgeStore(tmp_path / "ratings.csv", tmp_path / "notes.csv")
    store.initialize()
    allowed = {("allowed", "proposed")}
    with pytest.raises(ValueError, match="frozen human agreement sample"):
        store.save(
            _rating("outside", "proposed"),
            _note("outside", "proposed"),
            allowed,
        )


def test_production_manifest_reconstructs_exact_40_v2_inputs() -> None:
    corpus_path = ROOT / "data/processed/spotify_threads.jsonl"
    if not corpus_path.exists():
        pytest.skip(
            "requires the local processed TWCS corpus, which is intentionally gitignored"
        )
    manifest = json.loads(
        (ROOT / "data/manifests/human_judge_agreement_sample.json").read_text(
            encoding="utf-8"
        )
    )
    items = load_review_items(manifest["selected_keys"], corpus_path=corpus_path)
    assert len(items) == 40
    assert Counter(item.system for item in items) == {
        "proposed": 14,
        "lexical": 13,
        "fixed": 13,
    }
    assert all(item.customer and item.reply and item.action for item in items)
    assert all(len(item.evidence) <= 2 for item in items)

    primary_rows = [
        json.loads(line)
        for line in (ROOT / "results/dev_judge_v2_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert manifest["selected_keys"] == deterministic_sample(primary_rows)


def test_finalized_rating_requires_explicit_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = _items()
    store = HumanJudgeStore(tmp_path / "ratings.csv", tmp_path / "notes.csv")
    allowed = {(item.case_id, item.system) for item in items}
    first = items[0]
    store.initialize()
    store.save(_rating(first.case_id, first.system), _note(first.case_id, first.system), allowed)
    with pytest.raises(ValueError, match="already finalized"):
        store.save(
            _rating(first.case_id, first.system),
            _note(first.case_id, first.system),
            allowed,
        )

    _inputs(monkeypatch, ["5", "5", "5", "5", "5", "y", "Critical issue found."])
    run_review(items, store, revise_index=1)
    ratings, notes = store.load()
    assert ratings[(first.case_id, first.system)].overall_pass == "false"
    assert notes[(first.case_id, first.system)].critical_failure == "true"


def test_completed_file_runs_existing_agreement_script(
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        (ROOT / "data/manifests/human_judge_agreement_sample.json").read_text(
            encoding="utf-8"
        )
    )
    ratings_path = tmp_path / "human.csv"
    notes_path = tmp_path / "notes.csv"
    store = HumanJudgeStore(ratings_path, notes_path)
    store.initialize()
    allowed = {
        (str(row["case_id"]), str(row["system"])) for row in manifest["selected_keys"]
    }
    for case_id, system in sorted(allowed):
        store.save(_rating(case_id, system), _note(case_id, system), allowed)
    output = tmp_path / "agreement.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_judge_agreement.py",
            "--human",
            str(ratings_path),
            "--llm",
            "results/dev_judge_v2_results.jsonl",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "MEASURED"
    assert result["matched_rating_count"] == 40
