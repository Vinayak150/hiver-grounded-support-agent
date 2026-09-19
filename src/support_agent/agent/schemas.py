"""Structured Phase 4 agent outputs."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from support_agent.evaluation.schemas import Prediction
from support_agent.retrieval.hybrid import RetrievedCase


@dataclass(frozen=True)
class AgentOutput:
    case_id: str
    intent: str
    intent_confidence: float
    intent_alternatives: tuple[tuple[str, float], ...]
    retrieved_cases: tuple[RetrievedCase, ...]
    reply: str
    action: str
    action_reason: str
    reason_codes: tuple[str, ...]
    risk_tags: tuple[str, ...]
    evidence_sufficient: bool
    grounding_passed: bool
    latency_ms: float | None
    system_version: str
    evidence_ids: tuple[str, ...] | None = None

    def validate(self) -> None:
        if not all(
            (self.case_id, self.intent, self.reply, self.action_reason, self.system_version)
        ):
            raise ValueError("Required agent output fields cannot be empty.")
        if self.action not in {"AUTO_HANDLE", "ESCALATE"}:
            raise ValueError(f"Invalid action: {self.action}")
        if not 0.0 <= self.intent_confidence <= 1.0:
            raise ValueError("Intent confidence must be within [0, 1].")
        if self.latency_ms is not None and (
            not math.isfinite(self.latency_ms) or self.latency_ms < 0
        ):
            raise ValueError("Latency must be null or a non-negative finite value.")
        if self.action == "AUTO_HANDLE" and not (
            self.evidence_sufficient and self.grounding_passed
        ):
            raise ValueError("AUTO_HANDLE requires sufficient evidence and grounding.")

    def as_dict(self) -> dict[str, object]:
        self.validate()
        payload = asdict(self)
        payload["intent_alternatives"] = [
            {"intent": intent, "probability": probability}
            for intent, probability in self.intent_alternatives
        ]
        payload["retrieved_cases"] = [case.as_dict() for case in self.retrieved_cases]
        payload["reason_codes"] = list(self.reason_codes)
        payload["risk_tags"] = list(self.risk_tags)
        if self.evidence_ids is None:
            payload.pop("evidence_ids")
        else:
            payload["evidence_ids"] = list(self.evidence_ids)
        return payload

    def to_prediction(self) -> Prediction:
        evidence_ids = (
            self.evidence_ids
            if self.evidence_ids is not None
            else (self.retrieved_cases[0].thread_id,)
            if self.action == "AUTO_HANDLE"
            else ()
        )
        return Prediction(
            case_id=self.case_id,
            system_name=self.system_version,
            intent=self.intent,
            intent_confidence=self.intent_confidence,
            action=self.action,
            action_reason=self.action_reason,
            reply=self.reply,
            retrieved_thread_ids=tuple(case.thread_id for case in self.retrieved_cases),
            retrieval_scores=tuple(case.evidence_score for case in self.retrieved_cases),
            evidence_ids=evidence_ids,
            latency_ms=self.latency_ms,
            metadata={
                "evidence_sufficient": self.evidence_sufficient,
                "grounding_passed": self.grounding_passed,
                "reason_codes": list(self.reason_codes),
                "risk_tags": list(self.risk_tags),
            },
        )
