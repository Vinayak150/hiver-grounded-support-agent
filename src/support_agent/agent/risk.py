"""Deterministic conservative risk classification."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskAssessment:
    tags: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def high_risk(self) -> bool:
        return bool(self.tags)


_REASONS = {
    "SECURITY": "SECURITY_RISK",
    "PAYMENT": "PAYMENT_ACTION_REQUIRED",
    "REFUND": "PAYMENT_ACTION_REQUIRED",
    "PRIVATE_LOOKUP": "PRIVATE_ACCOUNT_REQUIRED",
    "PII": "PRIVATE_ACCOUNT_REQUIRED",
    "ACCOUNT_SPECIFIC": "PRIVATE_ACCOUNT_REQUIRED",
    "POLICY_SENSITIVE": "UNSUPPORTED_POLICY_RISK",
    "LOW_CONTEXT": "LOW_CONTEXT",
    "MULTI_INTENT": "AMBIGUOUS_INTENT",
}


def assess_risk(
    text: str,
    margin: float,
    config: dict[str, object],
    predicted_intent: str | None = None,
) -> RiskAssessment:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    tags = []
    marker_groups = (
        ("SECURITY", "security_markers"),
        ("PAYMENT", "payment_markers"),
        ("REFUND", "refund_markers"),
        ("PRIVATE_LOOKUP", "private_lookup_markers"),
        ("PII", "pii_markers"),
        ("ACCOUNT_SPECIFIC", "account_specific_markers"),
        ("POLICY_SENSITIVE", "policy_sensitive_markers"),
    )
    for tag, key in marker_groups:
        if any(str(marker) in normalized for marker in config[key]):
            tags.append(tag)
    if predicted_intent == "billing_or_payment":
        tags.append("PAYMENT")
    if predicted_intent == "account_access_or_security":
        tags.append("ACCOUNT_SPECIFIC")
    tokens = re.findall(r"[a-z0-9']+", normalized)
    if len(tokens) <= int(config["low_context_maximum_tokens"]):
        tags.append("LOW_CONTEXT")
    if margin < float(config["ambiguous_intent_margin"]):
        tags.append("MULTI_INTENT")
    unique_tags = tuple(dict.fromkeys(tags))
    return RiskAssessment(
        tags=unique_tags,
        reason_codes=tuple(dict.fromkeys(_REASONS[tag] for tag in unique_tags)),
    )
