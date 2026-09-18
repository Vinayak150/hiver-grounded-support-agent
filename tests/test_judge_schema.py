from __future__ import annotations

import json

import pytest

from support_agent.judge.schema import JudgeResult


def valid_payload() -> dict[str, object]:
    return {
        "case_id": "dev-1",
        "groundedness_score": 4,
        "relevance_score": 4,
        "helpfulness_score": 3,
        "safety_score": 5,
        "brand_context_score": 4,
        "overall_pass": True,
        "critical_failure": False,
        "failure_reasons": [],
        "short_rationale": "The response is supported and safely asks for clarification.",
        "judge_model": "test-model",
        "rubric_version": "support-response-rubric-v1",
        "prompt_version": "blinded-absolute-v1",
    }


def test_strict_judge_schema_accepts_valid_output():
    result = JudgeResult.from_json(json.dumps(valid_payload()))
    assert result.overall_pass
    assert result.as_dict()["failure_reasons"] == []


def test_invalid_score_is_rejected():
    payload = valid_payload()
    payload["safety_score"] = 6
    with pytest.raises(ValueError, match="safety_score"):
        JudgeResult.from_json(json.dumps(payload))


def test_missing_dimension_and_extra_field_are_rejected():
    payload = valid_payload()
    del payload["helpfulness_score"]
    payload["unexpected"] = "value"
    with pytest.raises(ValueError, match="fields mismatch"):
        JudgeResult.from_json(json.dumps(payload))


def test_pass_rule_and_critical_failure_reason_are_enforced():
    payload = valid_payload()
    payload["safety_score"] = 2
    with pytest.raises(ValueError, match="overall_pass"):
        JudgeResult.from_json(json.dumps(payload))
    payload["overall_pass"] = False
    payload["critical_failure"] = True
    with pytest.raises(ValueError, match="requires"):
        JudgeResult.from_json(json.dumps(payload))
