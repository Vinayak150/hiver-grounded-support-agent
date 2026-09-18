from __future__ import annotations

import json

import pytest

from support_agent.judge.prompts_v2 import ABSOLUTE_PREFIX, compact_absolute_messages
from support_agent.judge.schema_v2 import CompactJudgeResult, compact_judge_schema


def valid_v2_payload() -> dict[str, object]:
    return {
        "groundedness": 4,
        "relevance": 4,
        "helpfulness": 3,
        "safety": 5,
        "brand_context": 4,
        "overall_pass": True,
        "critical_failure": False,
        "failure_codes": [],
        "rationale": "Supported, relevant, and safe.",
    }


def test_compact_v2_schema_and_pass_rule():
    result = CompactJudgeResult.from_json(json.dumps(valid_v2_payload()))
    assert result.overall_pass
    assert compact_judge_schema()["additionalProperties"] is False
    invalid = valid_v2_payload()
    invalid["safety"] = 2
    normalized = CompactJudgeResult.from_json(json.dumps(invalid))
    assert normalized.overall_pass is False


def test_compact_v2_rationale_is_at_most_twenty_words():
    payload = valid_v2_payload()
    payload["rationale"] = "word " * 21
    with pytest.raises(ValueError, match="1 to 20"):
        CompactJudgeResult.from_json(json.dumps(payload))


def test_v2_constant_prefix_is_byte_identical_and_blinded():
    first = compact_absolute_messages(
        customer="Playback stops.",
        reply="Restart the app.",
        action="AUTO_HANDLE",
        evidence=("Restarting may help.",),
    )
    second = compact_absolute_messages(
        customer="I was charged.",
        reply="A specialist should review this.",
        action="ESCALATE",
        evidence=(),
    )
    assert first[0]["content"] == second[0]["content"] == ABSOLUTE_PREFIX
    assert "case_id" not in ABSOLUTE_PREFIX.casefold()
    assert "proposed" not in ABSOLUTE_PREFIX.casefold()
    assert "Playback stops" not in ABSOLUTE_PREFIX
