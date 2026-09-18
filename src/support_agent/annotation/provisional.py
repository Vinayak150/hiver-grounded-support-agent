"""Conservative AI-provisional suggestions; never human benchmark labels."""

from __future__ import annotations

import re
from collections import Counter

from support_agent.taxonomy.schema import Taxonomy

from .schema import (
    AIProvisionalLabel,
    FrozenCandidate,
    HumanAnnotation,
    build_human_annotation,
)

TOKEN_RE = re.compile(r"[a-z][a-z']+")


def customer_only_text(case: FrozenCandidate) -> str:
    turns = [
        value.removeprefix("CUSTOMER: ")
        for value in case.conversation_context.split(" || ")
        if value.startswith("CUSTOMER: ")
    ]
    return " ".join(turns) if turns else case.customer_message


def _signal_present(text: str, signal: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(signal.casefold())}(?![a-z0-9])", text))


def intent_scores(text: str, taxonomy: Taxonomy) -> dict[str, int]:
    normalized = re.sub(r"\s+", " ", text.casefold())
    return {
        intent.id: sum(_signal_present(normalized, signal) for signal in intent.common_signals)
        for intent in taxonomy.intents
        if intent.id != taxonomy.default_intent
    }


def _risk_tags(text: str, scored_intents: list[str], token_count: int) -> set[str]:
    normalized = text.casefold()
    tags = set()
    if any(term in normalized for term in ("my account", "account", "username", "log in", "login")):
        tags.add("ACCOUNT_SPECIFIC")
    if any(
        term in normalized for term in ("charged", "charge", "payment", "card", "billing", "paypal")
    ):
        tags.add("PAYMENT")
    if "refund" in normalized:
        tags.add("REFUND")
    if any(term in normalized for term in ("hack", "breach", "compromised", "stolen password")):
        tags.add("SECURITY")
    if any(term in normalized for term in ("email address", "username", "phone number", "<email>")):
        tags.add("PII")
    if any(
        term in normalized
        for term in ("refund", "eligible", "eligibility", "policy", "available in")
    ):
        tags.add("POLICY_SENSITIVE")
    if any(
        term in normalized
        for term in ("my account", "charged", "refund", "hacked", "breach", "look into")
    ):
        tags.add("PRIVATE_LOOKUP")
    if len(scored_intents) >= 3:
        tags.add("MULTI_INTENT")
    if any(
        term in normalized
        for term in ("iphone", "android", "windows", "mac", "speaker", "sonos", "xbox")
    ):
        tags.add("DEVICE_CONTEXT")
    if token_count <= 5:
        tags.add("LOW_CONTEXT")
    return tags


def propose_label(
    case: FrozenCandidate,
    taxonomy: Taxonomy,
    config: dict[str, object],
    risk_tag_order: tuple[str, ...],
) -> AIProvisionalLabel:
    text = customer_only_text(case)
    tokens = TOKEN_RE.findall(text.casefold())
    scores = intent_scores(text, taxonomy)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], taxonomy.intent_ids.index(item[0])))
    top_score = ranked[0][1]
    tied = [intent_id for intent_id, score in ranked if score == top_score and score > 0]
    active = [intent_id for intent_id, score in ranked if score > 0]
    flags = set()
    if top_score == 0:
        suggested_intent = "UNSURE"
        intent_confidence = 0.20
        flags.add("NO_TAXONOMY_SIGNAL")
    elif len(tied) > 1:
        suggested_intent = "UNSURE"
        intent_confidence = 0.35
        flags.update({"INTENT_TIE", "TAXONOMY_BOUNDARY"})
    else:
        suggested_intent = ranked[0][0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        gap = top_score - second_score
        intent_confidence = min(0.94, 0.54 + 0.12 * top_score + 0.06 * gap)
        if len(active) > 1:
            flags.add("MULTI_INTENT_SIGNAL")
        if gap <= 1 and len(active) > 1:
            flags.add("TAXONOMY_BOUNDARY")
    if intent_confidence < float(config["low_intent_confidence"]):
        flags.add("LOW_INTENT_CONFIDENCE")
    if len(tokens) <= 5:
        flags.add("LOW_CONTEXT")
    tags = _risk_tags(text, active, len(tokens))
    if suggested_intent == "UNSURE":
        tags.add("AMBIGUOUS")
    escalation_tags = {
        "ACCOUNT_SPECIFIC",
        "PAYMENT",
        "REFUND",
        "SECURITY",
        "PII",
        "POLICY_SENSITIVE",
        "PRIVATE_LOOKUP",
        "MULTI_INTENT",
        "AMBIGUOUS",
    }
    must_escalate = bool(tags & escalation_tags) or suggested_intent in {
        "UNSURE",
        "account_access_or_security",
        "billing_or_payment",
        taxonomy.default_intent,
    }
    if must_escalate:
        suggested_action = "ESCALATE"
        action_confidence = 0.94 if tags & escalation_tags else 0.82
        short_reason = (
            "Private, sensitive, policy-dependent, or ambiguous handling may be required; "
            "do not auto-handle without human confirmation."
        )
    else:
        suggested_action = "AUTO_HANDLE"
        action_confidence = 0.78 if intent_confidence >= 0.60 else 0.58
        short_reason = (
            "The visible request appears suitable for grounded public guidance without "
            "private account access or internal action."
        )
    if action_confidence < float(config["low_action_confidence"]):
        flags.add("LOW_ACTION_CONFIDENCE")
    ordered_tags = [tag for tag in risk_tag_order if tag in tags]
    return AIProvisionalLabel(
        case_id=case.case_id,
        suggested_intent=suggested_intent,
        intent_confidence=f"{intent_confidence:.2f}",
        suggested_action=suggested_action,
        action_confidence=f"{action_confidence:.2f}",
        suggested_risk_tags="|".join(ordered_tags),
        short_reason=short_reason,
        uncertainty_flags="|".join(sorted(flags)),
        model_name=str(config["model_name"]),
        prompt_version=str(config["prompt_version"]),
    )


def propose_labels(
    cases: list[FrozenCandidate],
    taxonomy: Taxonomy,
    config: dict[str, object],
    risk_tag_order: tuple[str, ...],
) -> list[AIProvisionalLabel]:
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Frozen case IDs must be unique before provisional labeling.")
    labels = [propose_label(case, taxonomy, config, risk_tag_order) for case in cases]
    if Counter(label.annotation_source for label in labels) != {"AI_PROVISIONAL": len(cases)}:
        raise ValueError("Provisional labeling produced a non-AI source.")
    return labels


def confirm_provisional_as_human(
    case: FrozenCandidate,
    label: AIProvisionalLabel,
    explicit_confirmation: bool,
    difficulty: str,
    annotation_notes: str = "",
) -> HumanAnnotation:
    """Convert a suggestion only after an explicit human confirmation event."""

    if not explicit_confirmation:
        raise ValueError("AI suggestions require explicit human confirmation before saving.")
    if "UNSURE" in {label.suggested_intent, label.suggested_action}:
        raise ValueError("UNSURE AI suggestions must be corrected, not accepted.")
    return build_human_annotation(
        case,
        explicit_human_input=True,
        gold_intent=label.suggested_intent,
        gold_action=label.suggested_action,
        gold_action_reason=label.short_reason,
        difficulty=difficulty,
        risk_tags=label.suggested_risk_tags,
        annotation_notes=annotation_notes,
    )
