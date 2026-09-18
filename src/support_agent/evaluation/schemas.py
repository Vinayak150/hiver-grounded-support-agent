"""Stable structured prediction records shared by every system."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Prediction:
    case_id: str
    system_name: str
    intent: str
    action: str
    action_reason: str
    reply: str
    intent_confidence: float | None = None
    retrieved_thread_ids: tuple[str, ...] = ()
    retrieval_scores: tuple[float, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("case_id", "system_name", "intent", "action", "action_reason", "reply"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"Prediction field is required: {name}")
        if self.action not in {"AUTO_HANDLE", "ESCALATE"}:
            raise ValueError(f"Invalid prediction action: {self.action}")
        if self.intent_confidence is not None and not 0.0 <= self.intent_confidence <= 1.0:
            raise ValueError("intent_confidence must be between zero and one.")
        if len(self.retrieved_thread_ids) != len(self.retrieval_scores):
            raise ValueError("Retrieved IDs and scores must have matching lengths.")
        if any(
            not math.isfinite(score) or not 0.0 <= score <= 1.0
            for score in self.retrieval_scores
        ):
            raise ValueError("Retrieval scores must be finite values between zero and one.")
        if self.latency_ms is not None and (
            not math.isfinite(self.latency_ms) or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be a non-negative finite value when supplied.")

    def as_dict(self) -> dict[str, object]:
        self.validate()
        payload = asdict(self)
        payload["retrieved_thread_ids"] = list(self.retrieved_thread_ids)
        payload["retrieval_scores"] = list(self.retrieval_scores)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload
