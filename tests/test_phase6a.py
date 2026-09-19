from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from support_agent.annotation.schema import ANNOTATION_FIELDS
from support_agent.annotation.store import load_frozen_candidates
from support_agent.evaluation.gold import validate_human_gold

ROOT = Path(__file__).resolve().parents[1]


def _gate(path: Path):
    return validate_human_gold(
        gold_path=path,
        candidates_path=ROOT / "data/annotations/final_golden_candidates.csv",
        frozen_manifest_path=ROOT / "data/manifests/final_golden_candidate_manifest.json",
        split_manifest_path=ROOT / "data/manifests/split_manifest.json",
        taxonomy_path=ROOT / "configs/taxonomy.yaml",
        annotation_config_path=ROOT / "configs/annotation.yaml",
    )


def _write_gold(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _valid_row() -> dict[str, str]:
    candidate = load_frozen_candidates(
        ROOT / "data/annotations/final_golden_candidates.csv"
    )[0]
    return {
        "case_id": candidate.case_id,
        "thread_id": candidate.thread_id,
        "taxonomy_version": candidate.taxonomy_version,
        "sampling_version": candidate.sampling_version,
        "split_version": candidate.split_version,
        "gold_intent": "other_or_unclear",
        "gold_action": "ESCALATE",
        "gold_action_reason": "Human reviewer determined escalation is required.",
        "difficulty": "MEDIUM",
        "risk_tags": "AMBIGUOUS",
        "annotation_notes": "Test fixture.",
        "annotator": "candidate",
        "reviewed_at": "2026-09-19T12:00:00+00:00",
        "annotation_source": "human",
        "status": "FINALIZED",
    }


def test_final_system_manifest_freezes_original_phase4() -> None:
    manifest = json.loads(
        (ROOT / "data/manifests/final_system_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["final_system_version"] == "spotify-grounded-agent-v1.0-final-candidate"
    assert manifest["retained_candidate"] == "ORIGINAL_PHASE_4"
    assert manifest["default_config"] == "configs/agent.yaml"
    assert manifest["phase41_status"] == "REJECTED"
    assert manifest["protection"]["phase41_is_default"] is False


def test_current_gold_gate_is_ready_at_200() -> None:
    result = _gate(ROOT / "data/annotations/golden_annotations.csv")
    assert result.status == "READY"
    assert result.human_label_count == 200
    assert result.required_minimum == 150
    assert result.final_evaluation_ready is True


def test_gold_gate_rejects_ai_provisional_as_human(tmp_path: Path) -> None:
    row = _valid_row()
    row["annotation_source"] = "AI_PROVISIONAL"
    path = tmp_path / "gold.csv"
    _write_gold(path, [row])
    result = _gate(path)
    assert result.final_evaluation_ready is False
    assert any("not explicit human" in error for error in result.errors)


def test_gold_gate_refuses_fewer_than_150_human_rows(tmp_path: Path) -> None:
    path = tmp_path / "gold.csv"
    _write_gold(path, [_valid_row()])
    result = _gate(path)
    assert result.final_evaluation_ready is False
    assert any("between 150 and 250" in error for error in result.errors)


def test_final_eval_fails_before_generating_predictions(tmp_path: Path) -> None:
    incomplete_gold = tmp_path / "incomplete_gold.csv"
    _write_gold(incomplete_gold, [])
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_final_evaluation.py",
            "--gold",
            str(incomplete_gold),
            "--output-dir",
            str(tmp_path / "final"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "FINAL_EVALUATION_READY=NO" in completed.stdout
    assert not (tmp_path / "final").exists()


def test_demo_output_is_deterministic(tmp_path: Path) -> None:
    outputs = []
    for name in ("one.json", "two.json"):
        path = tmp_path / name
        completed = subprocess.run(
            [sys.executable, "scripts/run_demo.py", "--output", str(path)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "DEMO_DATA=SYNTHETIC_SANITIZED_NOT_BENCHMARK" in completed.stdout
        outputs.append(path.read_bytes())
    assert outputs[0] == outputs[1]
    payload = json.loads(outputs[0])
    assert {row["action"] for row in payload["outputs"]} == {"AUTO_HANDLE", "ESCALATE"}


def test_submission_validator_separates_engineering_and_gold(tmp_path: Path) -> None:
    output = tmp_path / "validation.json"
    completed = subprocess.run(
        [sys.executable, "scripts/validate_submission.py", "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["engineering_submission_ready"] is True
    assert result["final_evaluation_ready"] is True
    assert result["human_gold_count"] == 200
