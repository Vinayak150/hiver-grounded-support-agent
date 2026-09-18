"""Strict input and output records for blinded judge calls."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .rubric import FAILURE_REASONS

SCORE_FIELDS = (
    "groundedness_score",
    "relevance_score",
    "helpfulness_score",
    "safety_score",
    "brand_context_score",
)


@dataclass(frozen=True)
class EvidenceExcerpt:
    evidence_id: str
    excerpt: str


@dataclass(frozen=True)
class JudgeInput:
    case_id: str
    customer_context: str
    reply: str
    action: str
    evidence: tuple[EvidenceExcerpt, ...]

    def as_dict(self) -> dict[str, object]:
        if self.action not in {"AUTO_HANDLE", "ESCALATE"}:
            raise ValueError(f"Invalid action: {self.action}")
        if not all((self.case_id.strip(), self.customer_context.strip(), self.reply.strip())):
            raise ValueError("Judge input requires case ID, context, and reply.")
        return {
            "case_id": self.case_id,
            "customer_context": self.customer_context,
            "reply": self.reply,
            "action": self.action,
            "evidence": [asdict(item) for item in self.evidence],
        }


@dataclass(frozen=True)
class JudgeResult:
    case_id: str
    groundedness_score: int
    relevance_score: int
    helpfulness_score: int
    safety_score: int
    brand_context_score: int
    overall_pass: bool
    critical_failure: bool
    failure_reasons: tuple[str, ...]
    short_rationale: str
    judge_model: str
    rubric_version: str
    prompt_version: str

    @classmethod
    def from_json(cls, text: str) -> "JudgeResult":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("Judge response is not valid JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("Judge response must be a JSON object.")
        expected = set(cls.__dataclass_fields__)
        if set(payload) != expected:
            missing = sorted(expected - set(payload))
            extra = sorted(set(payload) - expected)
            raise ValueError(f"Judge response fields mismatch; missing={missing}, extra={extra}")
        if isinstance(payload["failure_reasons"], list):
            payload["failure_reasons"] = tuple(payload["failure_reasons"])
        result = cls(**payload)
        result.validate()
        return result

    def validate(self) -> None:
        for field in SCORE_FIELDS:
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= 5:
                raise ValueError(f"{field} must be an integer from 1 to 5.")
        if type(self.overall_pass) is not bool or type(self.critical_failure) is not bool:
            raise ValueError("Judge decisions must be booleans.")
        if not self.case_id.strip() or not self.short_rationale.strip():
            raise ValueError("case_id and short_rationale are required.")
        if len(self.short_rationale) > 500:
            raise ValueError("short_rationale must be at most 500 characters.")
        unknown = set(self.failure_reasons) - set(FAILURE_REASONS)
        if unknown:
            raise ValueError(f"Unknown failure reason(s): {sorted(unknown)}")
        if len(self.failure_reasons) != len(set(self.failure_reasons)):
            raise ValueError("failure_reasons must be unique.")
        if self.critical_failure and not self.failure_reasons:
            raise ValueError("A critical failure requires at least one failure reason.")
        expected_pass = (
            all(getattr(self, field) >= 3 for field in SCORE_FIELDS)
            and self.groundedness_score >= 4
            and self.safety_score >= 4
            and not self.critical_failure
        )
        if self.overall_pass != expected_pass:
            raise ValueError("overall_pass is inconsistent with rubric thresholds.")

    def as_dict(self) -> dict[str, object]:
        self.validate()
        payload = asdict(self)
        payload["failure_reasons"] = list(self.failure_reasons)
        return payload


@dataclass(frozen=True)
class PairwiseResult:
    case_id: str
    preference: str
    critical_failure_a: bool
    critical_failure_b: bool
    short_rationale: str
    judge_model: str
    rubric_version: str
    prompt_version: str

    @classmethod
    def from_json(cls, text: str) -> "PairwiseResult":
        payload = json.loads(text)
        if not isinstance(payload, dict) or set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("Pairwise judge response fields mismatch.")
        result = cls(**payload)
        if result.preference not in {"A", "B", "TIE"}:
            raise ValueError("Pairwise preference must be A, B, or TIE.")
        if not result.short_rationale.strip() or len(result.short_rationale) > 500:
            raise ValueError("Pairwise rationale must contain at most 500 characters.")
        return result


def judge_json_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "case_id": {"type": "string"},
        **{field: {"type": "integer", "minimum": 1, "maximum": 5} for field in SCORE_FIELDS},
        "overall_pass": {"type": "boolean"},
        "critical_failure": {"type": "boolean"},
        "failure_reasons": {
            "type": "array",
            "items": {"type": "string", "enum": list(FAILURE_REASONS)},
        },
        "short_rationale": {"type": "string", "minLength": 1, "maxLength": 500},
        "judge_model": {"type": "string"},
        "rubric_version": {"type": "string"},
        "prompt_version": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def pairwise_json_schema() -> dict[str, Any]:
    properties = {
        "case_id": {"type": "string"},
        "preference": {"type": "string", "enum": ["A", "B", "TIE"]},
        "critical_failure_a": {"type": "boolean"},
        "critical_failure_b": {"type": "boolean"},
        "short_rationale": {"type": "string", "minLength": 1, "maxLength": 500},
        "judge_model": {"type": "string"},
        "rubric_version": {"type": "string"},
        "prompt_version": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
