"""End-to-end deterministic grounded support agent."""

from __future__ import annotations

from support_agent.agent.evidence import EvidenceThresholds, assess_evidence
from support_agent.agent.risk import assess_risk
from support_agent.agent.schemas import AgentOutput
from support_agent.classification.classifier import IntentClassifier, IntentPrediction
from support_agent.data.spotify import SupportThread
from support_agent.generation.grounded import GroundedComposer
from support_agent.generation.verifier import GroundingVerifier, VerificationResult
from support_agent.retrieval.hybrid import HybridRetriever, RetrievedCase

_REASON_TEXT = {
    "LOW_INTENT_CONFIDENCE": "Intent confidence is below the DEVELOPMENT heuristic threshold.",
    "AMBIGUOUS_INTENT": "The intent prediction is ambiguous.",
    "INSUFFICIENT_EVIDENCE": "Historical public evidence is below the sufficiency threshold.",
    "INTENT_RETRIEVAL_MISMATCH": (
        "Retrieved cases do not sufficiently agree with the predicted intent."
    ),
    "TEMPLATE_CONCENTRATION": "Retrieved evidence is overly concentrated in one reply template.",
    "PRIVATE_ACCOUNT_REQUIRED": "The request may require private or account-specific handling.",
    "SECURITY_RISK": "The request contains a security-sensitive issue.",
    "PAYMENT_ACTION_REQUIRED": "The request may require payment or refund action.",
    "UNSUPPORTED_POLICY_RISK": "The request may require a current policy determination.",
    "LOW_CONTEXT": "The request lacks enough context for safe automation.",
    "GROUNDING_FAILURE": "The proposed reply did not pass evidence grounding checks.",
    "PII_LEAK": "The proposed reply contains a private identifier, handle, or URL.",
    "UNSUPPORTED_ACTION_CLAIM": "The proposed reply claims an unsupported action.",
    "MISSING_EVIDENCE": "No usable supporting evidence is attached.",
    "INVALID_EVIDENCE_REFERENCE": "A supporting evidence reference is invalid.",
}


class GroundedSupportAgent:
    def __init__(
        self,
        classifier: IntentClassifier,
        retriever: HybridRetriever,
        thresholds: EvidenceThresholds,
        config: dict[str, object],
    ) -> None:
        self.classifier = classifier
        self.retriever = retriever
        self.thresholds = thresholds
        self.config = config
        self.composer = GroundedComposer(config["generation"], config["verifier"])
        self.verifier = GroundingVerifier(config["verifier"])

    def run_one(
        self,
        thread: SupportThread,
        prediction: IntentPrediction | None = None,
        cases: list[RetrievedCase] | None = None,
    ) -> AgentOutput:
        prediction = prediction or self.classifier.predict(thread)
        cases = cases if cases is not None else self.retriever.retrieve(thread, prediction.intent)
        risk = assess_risk(
            thread.customer_text(), prediction.margin, self.config["risk"], prediction.intent
        )
        evidence = assess_evidence(prediction, cases, risk, self.thresholds)
        evidence_ids = (cases[0].thread_id,) if evidence.sufficient and cases else ()
        draft = self.composer.compose(cases) if evidence.sufficient else ""
        verification = (
            self.verifier.verify(draft, cases, evidence_ids)
            if evidence.sufficient
            else VerificationResult(False, (), 0.0)
        )
        auto_handle = evidence.sufficient and verification.passed and not risk.high_risk
        reasons = tuple(dict.fromkeys(evidence.reason_codes + verification.reason_codes))
        if auto_handle:
            reasons = ()
        elif not reasons:
            reasons = ("GROUNDING_FAILURE",)
        action_reason = (
            "All deterministic intent, evidence, risk, grounding, and safety gates passed."
            if auto_handle
            else " ".join(
                _REASON_TEXT.get(code, code.replace("_", " ").title()) for code in reasons
            )
        )
        output = AgentOutput(
            case_id=thread.thread_id,
            intent=prediction.intent,
            intent_confidence=prediction.confidence,
            intent_alternatives=prediction.alternatives,
            retrieved_cases=tuple(cases),
            reply=draft if auto_handle else self.composer.escalation_reply,
            action="AUTO_HANDLE" if auto_handle else "ESCALATE",
            action_reason=action_reason,
            reason_codes=reasons,
            risk_tags=risk.tags,
            evidence_sufficient=evidence.sufficient,
            grounding_passed=verification.passed,
            latency_ms=None,
            system_version=str(self.config["version"]),
        )
        output.validate()
        output.to_prediction().validate()
        return output

    def run_many(
        self,
        threads: list[SupportThread],
        predictions: list[IntentPrediction] | None = None,
        retrievals: list[list[RetrievedCase]] | None = None,
    ) -> list[AgentOutput]:
        predictions = predictions or self.classifier.predict_many(threads)
        retrievals = retrievals or self.retriever.retrieve_many(
            threads, [prediction.intent for prediction in predictions]
        )
        return [
            self.run_one(thread, prediction, cases)
            for thread, prediction, cases in zip(threads, predictions, retrievals, strict=True)
        ]
