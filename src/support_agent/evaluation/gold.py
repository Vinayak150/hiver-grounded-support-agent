"""Fail-closed validation for the frozen human-gold evaluation cohort."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from support_agent.annotation.schema import (
    ANNOTATION_FIELDS,
    HumanAnnotation,
    validate_annotation,
)
from support_agent.annotation.store import load_frozen_candidates
from support_agent.taxonomy.schema import load_taxonomy


@dataclass(frozen=True)
class GoldValidationResult:
    status: str
    final_evaluation_ready: bool
    human_label_count: int
    required_minimum: int
    allowed_maximum: int
    frozen_candidate_count: int
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], [f"Human annotation file is missing: {path}"]
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != ANNOTATION_FIELDS:
            return [], ["Human annotation schema does not match the frozen contract."]
        return list(reader), []


def validate_human_gold(
    *,
    gold_path: Path,
    candidates_path: Path,
    frozen_manifest_path: Path,
    split_manifest_path: Path,
    taxonomy_path: Path,
    annotation_config_path: Path,
    minimum: int = 150,
    maximum: int = 250,
) -> GoldValidationResult:
    """Validate human labels without accepting partial, provisional, or leaked rows."""

    errors: list[str] = []
    rows, row_errors = _load_rows(gold_path)
    errors.extend(row_errors)
    candidates = load_frozen_candidates(candidates_path)
    candidate_map = {candidate.case_id: candidate for candidate in candidates}
    frozen_manifest = json.loads(frozen_manifest_path.read_text(encoding="utf-8"))
    split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    annotation_config = json.loads(annotation_config_path.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy(taxonomy_path)

    manifest_ids = list(frozen_manifest.get("case_ids", []))
    if len(candidates) != 200 or frozen_manifest.get("case_count") != 200:
        errors.append("Frozen final candidate set must contain exactly 200 cases.")
    if len(manifest_ids) != len(set(manifest_ids)) or set(manifest_ids) != set(candidate_map):
        errors.append("Frozen candidate CSV and manifest case IDs do not reconcile.")
    if frozen_manifest.get("brand") != "SpotifyCares" or taxonomy.brand != "SpotifyCares":
        errors.append("Frozen evaluation brand must be SpotifyCares.")

    case_ids = [row.get("case_id", "") for row in rows]
    if len(case_ids) != len(set(case_ids)):
        errors.append("Human annotation file contains duplicate case IDs.")
    if not minimum <= len(rows) <= maximum:
        errors.append(f"Human annotation count must be between {minimum} and {maximum}.")

    protected_ids = set(split_manifest["thread_ids"]["TRAIN"]) | set(
        split_manifest["thread_ids"]["DEVELOPMENT"]
    )
    actions = set(annotation_config["actions"])
    difficulties = set(annotation_config["difficulties"])
    risk_tags = set(annotation_config["risk_tags"])
    for number, raw in enumerate(rows, start=2):
        try:
            annotation = HumanAnnotation(**raw)
        except TypeError as error:
            errors.append(f"Row {number} is malformed: {error}")
            continue
        if annotation.annotation_source != "human":
            errors.append(f"Row {number} is not explicit human annotation.")
        if annotation.status != "FINALIZED":
            errors.append(f"Row {number} is unresolved or deferred.")
        try:
            validate_annotation(
                annotation, set(taxonomy.intent_ids), actions, difficulties, risk_tags
            )
        except ValueError as error:
            errors.append(f"Row {number}: {error}")
        candidate = candidate_map.get(annotation.case_id)
        if candidate is None:
            errors.append(f"Row {number} is outside the frozen candidate set.")
            continue
        if annotation.thread_id != candidate.thread_id:
            errors.append(f"Row {number} thread ID does not match its frozen case.")
        if annotation.thread_id in protected_ids:
            errors.append(f"Row {number} contains a TRAIN/DEVELOPMENT thread ID.")
        expected_versions = {
            "taxonomy_version": candidate.taxonomy_version,
            "sampling_version": candidate.sampling_version,
            "split_version": candidate.split_version,
        }
        for field, expected in expected_versions.items():
            if getattr(annotation, field) != expected:
                errors.append(f"Row {number} has invalid {field}.")
        if annotation.taxonomy_version != taxonomy.version:
            errors.append(f"Row {number} uses an unrecognized taxonomy version.")

    unique_errors = tuple(dict.fromkeys(errors))
    ready = not unique_errors
    return GoldValidationResult(
        status="READY" if ready else "BLOCKED",
        final_evaluation_ready=ready,
        human_label_count=len(rows),
        required_minimum=minimum,
        allowed_maximum=maximum,
        frozen_candidate_count=len(candidates),
        errors=unique_errors,
    )
