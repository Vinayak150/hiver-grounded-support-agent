"""Rule-based grounding and safety verification before automation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from support_agent.retrieval.hybrid import RetrievedCase


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    reason_codes: tuple[str, ...]
    evidence_token_coverage: float


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z']+", text.casefold()))


class GroundingVerifier:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config

    def verify(
        self,
        draft: str,
        cases: list[RetrievedCase],
        evidence_ids: tuple[str, ...],
    ) -> VerificationResult:
        normalized = draft.casefold()
        reasons = []
        if re.search(
            r"@[a-z0-9_]+|https?://|www\.|[\w.+-]+@[\w.-]+\.[a-z]{2,}|"
            r"\b\d{7,}\b|(?:^|\s)/[A-Z]{1,3}\b",
            draft,
            re.I,
        ):
            reasons.append("PII_LEAK")
        marker_codes = (
            ("unsupported_action_markers", "UNSUPPORTED_ACTION_CLAIM"),
            ("private_inspection_markers", "PRIVATE_ACCOUNT_REQUIRED"),
            ("payment_promise_markers", "PAYMENT_ACTION_REQUIRED"),
            ("policy_claim_markers", "UNSUPPORTED_POLICY_RISK"),
        )
        for key, code in marker_codes:
            if any(str(marker).casefold() in normalized for marker in self.config[key]):
                reasons.append(code)
        valid_ids = {case.thread_id for case in cases}
        if not draft.strip() or not cases or not evidence_ids:
            reasons.append("MISSING_EVIDENCE")
        if any(value not in valid_ids for value in evidence_ids):
            reasons.append("INVALID_EVIDENCE_REFERENCE")
        evidence_tokens = (
            set().union(*(_tokens(case.historical_reply) for case in cases)) if cases else set()
        )
        draft_tokens = _tokens(draft)
        coverage = len(draft_tokens & evidence_tokens) / len(draft_tokens) if draft_tokens else 0.0
        if coverage < float(self.config["minimum_evidence_token_coverage"]):
            reasons.append("GROUNDING_FAILURE")
        unique = tuple(dict.fromkeys(reasons))
        return VerificationResult(not unique, unique, round(coverage, 6))
