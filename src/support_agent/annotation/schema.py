"""Candidate and human annotation schemas with fail-closed validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateCase:
    case_id: str
    thread_id: str
    taxonomy_version: str
    sampling_version: str
    split_version: str
    sampling_bucket: str
    customer_message: str
    conversation_context: str
    challenge_proxies: str


@dataclass(frozen=True)
class HumanAnnotation:
    case_id: str
    thread_id: str
    taxonomy_version: str
    sampling_version: str
    split_version: str
    gold_intent: str
    gold_action: str
    gold_action_reason: str
    difficulty: str
    risk_tags: str
    annotation_notes: str
    annotation_source: str = "human"
    status: str = "FINALIZED"


CANDIDATE_FIELDS = tuple(CandidateCase.__dataclass_fields__)
ANNOTATION_FIELDS = tuple(HumanAnnotation.__dataclass_fields__)


def validate_candidate(case: CandidateCase) -> None:
    for field in (
        "case_id",
        "thread_id",
        "taxonomy_version",
        "sampling_version",
        "split_version",
        "sampling_bucket",
        "customer_message",
    ):
        if not getattr(case, field).strip():
            raise ValueError(f"Candidate field is required: {field}")
    if case.sampling_bucket not in {"REPRESENTATIVE", "CHALLENGE"}:
        raise ValueError(f"Invalid sampling bucket: {case.sampling_bucket}")


def validate_annotation(
    annotation: HumanAnnotation,
    intent_ids: set[str],
    actions: set[str],
    difficulties: set[str],
    risk_tags: set[str],
) -> None:
    if annotation.annotation_source != "human":
        raise ValueError("Finalized annotations must declare annotation_source=human.")
    if annotation.status != "FINALIZED":
        raise ValueError("Saved annotation rows must be FINALIZED.")
    if annotation.gold_intent not in intent_ids:
        raise ValueError(f"Invalid gold intent: {annotation.gold_intent}")
    if annotation.gold_action not in actions:
        raise ValueError(f"Invalid gold action: {annotation.gold_action}")
    if annotation.difficulty not in difficulties:
        raise ValueError(f"Invalid difficulty: {annotation.difficulty}")
    if not annotation.gold_action_reason.strip():
        raise ValueError("A gold action reason is required.")
    supplied_tags = {tag for tag in annotation.risk_tags.split("|") if tag}
    unknown = supplied_tags - risk_tags
    if unknown:
        raise ValueError(f"Invalid risk tags: {', '.join(sorted(unknown))}")


def build_human_annotation(
    case: CandidateCase,
    explicit_human_input: bool,
    **values: str,
) -> HumanAnnotation:
    if not explicit_human_input:
        raise ValueError("Finalized human rows require explicit annotation input.")
    return HumanAnnotation(
        case_id=case.case_id,
        thread_id=case.thread_id,
        taxonomy_version=case.taxonomy_version,
        sampling_version=case.sampling_version,
        split_version=case.split_version,
        gold_intent=values["gold_intent"],
        gold_action=values["gold_action"],
        gold_action_reason=values["gold_action_reason"],
        difficulty=values["difficulty"],
        risk_tags=values.get("risk_tags", ""),
        annotation_notes=values.get("annotation_notes", ""),
    )
