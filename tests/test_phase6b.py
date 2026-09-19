from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from support_agent.annotation.store import AnnotationStore

ROOT = Path(__file__).resolve().parents[1]


def _run_review(output: Path, entered: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/annotate.py",
            "--human-gold",
            "--limit",
            "1",
            "--output",
            str(output),
            *extra,
        ],
        cwd=ROOT,
        input=entered,
        capture_output=True,
        text=True,
    )


def test_blind_human_gold_review_records_provenance_and_hides_suggestion(
    tmp_path: Path,
) -> None:
    output = tmp_path / "gold.csv"
    completed = _run_review(
        output,
        "9\ne\n2\n\nNeeds human support because the request is unclear.\n",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "AI PROVISIONAL SUGGESTION" not in completed.stdout
    assert "POST-SAVE AI COMPARISON" in completed.stdout
    rows = AnnotationStore(output).load()
    assert len(rows) == 1
    annotation = next(iter(rows.values()))
    assert annotation.annotation_source == "human"
    assert annotation.annotator == "candidate"
    assert annotation.reviewed_at.endswith("+00:00")
    assert annotation.status == "FINALIZED"


def test_human_gold_review_resumes_at_next_case(tmp_path: Path) -> None:
    output = tmp_path / "gold.csv"
    first = _run_review(output, "9\ne\n2\n\nFirst independent decision.\n")
    second = _run_review(output, "1\na\n1\n\nSecond independent decision.\n")
    assert first.returncode == second.returncode == 0
    rows = AnnotationStore(output).load()
    assert len(rows) == 2
    assert "Progress: 2/200" in second.stdout


def test_previous_case_correction_replaces_row_atomically(tmp_path: Path) -> None:
    output = tmp_path / "gold.csv"
    initial = _run_review(output, "9\ne\n2\n\nInitial decision.\n")
    assert initial.returncode == 0
    correction = _run_review(
        output,
        "p\n1\ne\n2\n\nCorrected independent decision.\nq\n",
    )
    assert correction.returncode == 0, correction.stdout + correction.stderr
    assert "Previous case corrected and saved atomically." in correction.stdout
    rows = AnnotationStore(output).load()
    assert len(rows) == 1
    annotation = next(iter(rows.values()))
    assert annotation.gold_intent == "playback_or_app_behavior"
    assert annotation.gold_action_reason == "Corrected independent decision."
