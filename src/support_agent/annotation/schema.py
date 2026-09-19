"""Candidate and human annotation schemas with fail-closed validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


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
class FrozenCandidate:
    case_id: str
    thread_id: str
    customer_message: str
    conversation_context: str
    candidate_type: str
    timestamp: str
    taxonomy_version: str
    split_version: str
    sampling_version: str


@dataclass(frozen=True)
class AIProvisionalLabel:
    case_id: str
    suggested_intent: str
    intent_confidence: str
    suggested_action: str
    action_confidence: str
    suggested_risk_tags: str
    short_reason: str
    uncertainty_flags: str
    model_name: str
    prompt_version: str
    annotation_source: str = "AI_PROVISIONAL"


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
    annotator: str
    reviewed_at: str
    annotation_source: str = "human"
    status: str = "FINALIZED"


CANDIDATE_FIELDS = tuple(CandidateCase.__dataclass_fields__)
FROZEN_CANDIDATE_FIELDS = tuple(FrozenCandidate.__dataclass_fields__)
AI_PROVISIONAL_FIELDS = tuple(AIProvisionalLabel.__dataclass_fields__)
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


def validate_frozen_candidate(case: FrozenCandidate) -> None:
    for field in FROZEN_CANDIDATE_FIELDS:
        if not getattr(case, field).strip():
            raise ValueError(f"Frozen candidate field is required: {field}")
    if case.candidate_type not in {"REPRESENTATIVE", "CHALLENGE"}:
        raise ValueError(f"Invalid candidate type: {case.candidate_type}")


def validate_ai_provisional_label(
    label: AIProvisionalLabel,
    intent_ids: set[str],
    actions: set[str],
    risk_tags: set[str],
) -> None:
    if label.annotation_source != "AI_PROVISIONAL":
        raise ValueError("AI suggestions must declare annotation_source=AI_PROVISIONAL.")
    if label.suggested_intent not in intent_ids | {"UNSURE"}:
        raise ValueError(f"Invalid suggested intent: {label.suggested_intent}")
    if label.suggested_action not in actions | {"UNSURE"}:
        raise ValueError(f"Invalid suggested action: {label.suggested_action}")
    for field in ("intent_confidence", "action_confidence"):
        value = float(getattr(label, field))
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Confidence must be between zero and one: {field}")
    supplied_tags = {tag for tag in label.suggested_risk_tags.split("|") if tag}
    unknown = supplied_tags - risk_tags
    if unknown:
        raise ValueError(f"Invalid provisional risk tags: {', '.join(sorted(unknown))}")
    if (
        not label.short_reason.strip()
        or not label.model_name.strip()
        or not label.prompt_version.strip()
    ):
        raise ValueError("Provisional labels require a reason, model name, and prompt version.")


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
    if annotation.annotator != "candidate":
        raise ValueError("Human gold must identify annotator=candidate.")
    try:
        reviewed_at = datetime.fromisoformat(annotation.reviewed_at)
    except ValueError as error:
        raise ValueError("Human gold requires a valid reviewed_at timestamp.") from error
    if reviewed_at.tzinfo is None:
        raise ValueError("Human gold reviewed_at timestamp must include a timezone.")
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
    case: CandidateCase | FrozenCandidate,
    explicit_human_input: bool,
    annotator: str = "candidate",
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
        annotator=annotator,
        reviewed_at=datetime.now(UTC).isoformat(),
    )
