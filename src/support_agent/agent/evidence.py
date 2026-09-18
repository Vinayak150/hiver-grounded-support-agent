"""Distribution-calibrated evidence sufficiency gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from support_agent.agent.risk import RiskAssessment
from support_agent.classification.classifier import IntentPrediction
from support_agent.retrieval.hybrid import RetrievedCase


@dataclass(frozen=True)
class EvidenceThresholds:
    intent_confidence: float
    intent_margin: float
    retrieval_score: float
    customer_similarity: float
    minimum_intent_agreement: float
    maximum_template_concentration: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceAssessment:
    sufficient: bool
    reason_codes: tuple[str, ...]
    intent_agreement: float
    template_concentration: float


def _bounded_quantile(values: list[float], quantile: float, bounds: list[float]) -> float:
    raw = float(np.quantile(np.asarray(values, dtype=float), quantile))
    return round(min(max(raw, float(bounds[0])), float(bounds[1])), 6)


def calibrate_thresholds(
    predictions: list[IntentPrediction],
    retrievals: list[list[RetrievedCase]],
    config: dict[str, object],
) -> EvidenceThresholds:
    if (
        not predictions
        or len(predictions) != len(retrievals)
        or any(not cases for cases in retrievals)
    ):
        raise ValueError("Complete DEVELOPMENT predictions and retrievals are required.")
    return EvidenceThresholds(
        intent_confidence=_bounded_quantile(
            [item.confidence for item in predictions],
            float(config["intent_confidence_quantile"]),
            config["intent_confidence_bounds"],
        ),
        intent_margin=_bounded_quantile(
            [item.margin for item in predictions],
            float(config["intent_margin_quantile"]),
            config["intent_margin_bounds"],
        ),
        retrieval_score=_bounded_quantile(
            [items[0].evidence_score for items in retrievals],
            float(config["retrieval_score_quantile"]),
            config["retrieval_score_bounds"],
        ),
        customer_similarity=_bounded_quantile(
            [items[0].similarity for items in retrievals],
            float(config["customer_similarity_quantile"]),
            config["customer_similarity_bounds"],
        ),
        minimum_intent_agreement=float(config["minimum_intent_agreement"]),
        maximum_template_concentration=float(config["maximum_template_concentration"]),
    )


def assess_evidence(
    prediction: IntentPrediction,
    cases: list[RetrievedCase],
    risk: RiskAssessment,
    thresholds: EvidenceThresholds,
) -> EvidenceAssessment:
    if not cases:
        return EvidenceAssessment(False, ("INSUFFICIENT_EVIDENCE",), 0.0, 1.0)
    agreement = sum(case.intent == prediction.intent for case in cases) / len(cases)
    most_common_template = max(
        sum(other.historical_reply == case.historical_reply for other in cases) for case in cases
    )
    concentration = most_common_template / len(cases)
    reasons = list(risk.reason_codes)
    if prediction.confidence < thresholds.intent_confidence:
        reasons.append("LOW_INTENT_CONFIDENCE")
    if prediction.margin < thresholds.intent_margin:
        reasons.append("AMBIGUOUS_INTENT")
    if (
        cases[0].evidence_score < thresholds.retrieval_score
        or cases[0].similarity < thresholds.customer_similarity
    ):
        reasons.append("INSUFFICIENT_EVIDENCE")
    if agreement < thresholds.minimum_intent_agreement:
        reasons.append("INTENT_RETRIEVAL_MISMATCH")
    if concentration > thresholds.maximum_template_concentration:
        reasons.append("TEMPLATE_CONCENTRATION")
    reasons = list(dict.fromkeys(reasons))
    return EvidenceAssessment(
        sufficient=not reasons,
        reason_codes=tuple(reasons),
        intent_agreement=round(agreement, 6),
        template_concentration=round(concentration, 6),
    )
