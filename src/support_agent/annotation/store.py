"""Resumable, atomic CSV storage for explicit human annotations."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from .schema import (
    AI_PROVISIONAL_FIELDS,
    ANNOTATION_FIELDS,
    CANDIDATE_FIELDS,
    FROZEN_CANDIDATE_FIELDS,
    AIProvisionalLabel,
    CandidateCase,
    FrozenCandidate,
    HumanAnnotation,
)


def load_candidates(path: Path) -> list[CandidateCase]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CANDIDATE_FIELDS:
            raise ValueError("Candidate queue schema does not match the Phase 2 contract.")
        rows = [CandidateCase(**row) for row in reader]
    if len({row.case_id for row in rows}) != len(rows):
        raise ValueError("Candidate queue contains duplicate case IDs.")
    if len({row.thread_id for row in rows}) != len(rows):
        raise ValueError("Candidate queue contains duplicate thread IDs.")
    return rows


def load_frozen_candidates(path: Path) -> list[FrozenCandidate]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FROZEN_CANDIDATE_FIELDS:
            raise ValueError("Frozen candidate schema does not match the Phase 2.6 contract.")
        rows = [FrozenCandidate(**row) for row in reader]
    if len({row.case_id for row in rows}) != len(rows):
        raise ValueError("Frozen candidates contain duplicate case IDs.")
    if len({row.thread_id for row in rows}) != len(rows):
        raise ValueError("Frozen candidates contain duplicate thread IDs.")
    return rows


def load_ai_provisional_labels(path: Path) -> dict[str, AIProvisionalLabel]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != AI_PROVISIONAL_FIELDS:
            raise ValueError("AI provisional schema does not match the Phase 2.6 contract.")
        rows = [AIProvisionalLabel(**row) for row in reader]
    if len({row.case_id for row in rows}) != len(rows):
        raise ValueError("AI provisional labels contain duplicate case IDs.")
    return {row.case_id: row for row in rows}


def golden_set_status(confirmed_count: int, minimum: int = 150) -> str:
    return (
        "READY_FOR_FINAL_EVALUATION"
        if confirmed_count >= minimum
        else "AWAITING_HUMAN_CONFIRMATION"
    )


class AnnotationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, HumanAnnotation]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {}
        with self.path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != ANNOTATION_FIELDS:
                raise ValueError("Annotation file schema does not match the Phase 2 contract.")
            rows = [HumanAnnotation(**row) for row in reader]
        if len({row.case_id for row in rows}) != len(rows):
            raise ValueError("Annotation file contains duplicate case IDs.")
        return {row.case_id: row for row in rows}

    def initialize(self) -> None:
        if self.path.exists():
            return
        self._write([])

    def save(self, annotation: HumanAnnotation, explicit_human_input: bool) -> None:
        if not explicit_human_input:
            raise ValueError("Cannot save a finalized row without explicit human input.")
        rows = self.load()
        if annotation.case_id in rows:
            raise ValueError(f"Case already annotated: {annotation.case_id}")
        rows[annotation.case_id] = annotation
        self._write([rows[key] for key in sorted(rows)])

    def replace(self, annotation: HumanAnnotation, explicit_human_input: bool) -> None:
        """Atomically replace one existing row after an explicit human correction."""

        if not explicit_human_input:
            raise ValueError("Cannot replace a finalized row without explicit human input.")
        rows = self.load()
        if annotation.case_id not in rows:
            raise ValueError(f"Cannot correct an unannotated case: {annotation.case_id}")
        rows[annotation.case_id] = annotation
        self._write([rows[key] for key in sorted(rows)])

    def progress(self, candidates: list[CandidateCase]) -> tuple[int, int, str | None]:
        completed = self.load()
        next_case = next(
            (case.case_id for case in candidates if case.case_id not in completed), None
        )
        completed_in_queue = sum(case.case_id in completed for case in candidates)
        return completed_in_queue, len(candidates), next_case

    def _write(self, rows: list[HumanAnnotation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(row.__dict__ for row in rows)
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
