"""Blinded, versioned judge prompts."""

from __future__ import annotations

import json

from .rubric import FAILURE_REASONS, RUBRIC_TEXT
from .schema import JudgeInput


def absolute_messages(
    item: JudgeInput, *, model: str, rubric_version: str, prompt_version: str
) -> list[dict[str, str]]:
    payload = item.as_dict()
    instructions = (
        "You are an independent support-response evaluator. Use only the supplied input and "
        "rubric. Historical evidence is not guaranteed current policy. Return only schema-valid "
        "JSON. Do not infer the generating system or expected answer. "
        f"Allowed failure reasons: {', '.join(FAILURE_REASONS)}. "
        f"Set judge_model={model}, rubric_version={rubric_version}, "
        f"prompt_version={prompt_version}.\n\n{RUBRIC_TEXT}"
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def pairwise_messages(
    *,
    case_id: str,
    customer_context: str,
    action_a: str,
    reply_a: str,
    action_b: str,
    reply_b: str,
    evidence: list[dict[str, str]],
    model: str,
    rubric_version: str,
    prompt_version: str,
) -> list[dict[str, str]]:
    payload = {
        "case_id": case_id,
        "customer_context": customer_context,
        "response_a": {"action": action_a, "reply": reply_a},
        "response_b": {"action": action_b, "reply": reply_b},
        "evidence": evidence,
    }
    instructions = (
        "Compare two anonymous support responses using the rubric. Prefer A, B, or TIE. "
        "Use only supplied context/evidence; system identity is intentionally hidden. Return "
        "only schema-valid JSON. "
        f"Set judge_model={model}, rubric_version={rubric_version}, "
        f"prompt_version={prompt_version}.\n\n{RUBRIC_TEXT}"
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]
