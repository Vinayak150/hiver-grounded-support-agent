from __future__ import annotations

import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from support_agent.data.protection import assert_no_frozen_thread_ids
from support_agent.data.spotify import SupportThread, Turn
from support_agent.judge.cache import JudgeCache
from support_agent.judge.provider import (
    OpenAICompatibleProvider,
    ProviderError,
    ProviderResponse,
    _is_daily_token_quota_error,
    _retry_after_seconds,
    _sanitize_provider_message,
)
from support_agent.judge.runner import JudgeRunError, JudgeRunner
from support_agent.judge.sampling import build_development_sample
from support_agent.judge.schema import EvidenceExcerpt, JudgeInput


def valid_response() -> str:
    return json.dumps(
        {
            "case_id": "dev-1",
            "groundedness_score": 4,
            "relevance_score": 4,
            "helpfulness_score": 3,
            "safety_score": 5,
            "brand_context_score": 4,
            "overall_pass": True,
            "critical_failure": False,
            "failure_reasons": [],
            "short_rationale": "Supported, relevant, and safe.",
            "judge_model": "test-model",
            "rubric_version": "support-response-rubric-v1",
            "prompt_version": "blinded-absolute-v1",
        }
    )


def valid_pairwise_response() -> str:
    return json.dumps(
        {
            "case_id": "dev-1",
            "preference": "A",
            "critical_failure_a": False,
            "critical_failure_b": False,
            "short_rationale": "Response A is more directly supported.",
            "judge_model": "test-model",
            "rubric_version": "support-response-rubric-v1",
            "prompt_version": "blinded-pairwise-v1",
        }
    )


def config() -> dict[str, object]:
    return {
        "model": "test-model",
        "rubric_version": "support-response-rubric-v1",
        "prompt_version": "blinded-absolute-v1",
        "pairwise_prompt_version": "blinded-pairwise-v1",
        "max_retries": 2,
    }


def judge_input() -> JudgeInput:
    return JudgeInput(
        "dev-1",
        "Music stops after pressing play on my phone.",
        "Can you try restarting the app?",
        "AUTO_HANDLE",
        (EvidenceExcerpt("train-1", "Please try restarting the app."),),
    )


class FakeProvider:
    model = "test-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, schema, schema_name):
        self.calls.append((messages, schema, schema_name))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return ProviderResponse(response, {"total_tokens": 17})


def support_thread(identifier: str) -> SupportThread:
    return SupportThread(
        identifier,
        identifier,
        2,
        1,
        1,
        "2020-01-01T00:00:00+00:00",
        "2020-01-01T00:01:00+00:00",
        2,
        (
            Turn("1", "CUSTOMER", "The app has a playback problem on my phone", "t", None),
            Turn("2", "SPOTIFY", "Please restart the app", "t", "1"),
        ),
    )


def test_retry_cache_and_blinded_prompt(tmp_path):
    invalid = json.loads(valid_response())
    invalid["groundedness_score"] = 9
    provider = FakeProvider([json.dumps(invalid), valid_response()])
    runner = JudgeRunner(provider, JudgeCache(tmp_path / "cache"), config())
    result = runner.evaluate(judge_input())
    assert result.overall_pass
    assert runner.stats.retries == 1
    assert len(provider.calls) == 2
    prompt = json.dumps(provider.calls[-1][0]).casefold()
    assert "fixed baseline" not in prompt
    assert "lexical baseline" not in prompt
    assert "proposed agent" not in prompt
    assert runner.evaluate(judge_input()) == result
    assert runner.stats.cache_hits == 1
    assert len(provider.calls) == 2


def test_provider_failure_creates_no_fake_result_or_cache(tmp_path):
    provider = FakeProvider([ProviderError("failure")] * 3)
    cache_path = tmp_path / "cache"
    runner = JudgeRunner(provider, JudgeCache(cache_path), config())
    with pytest.raises(JudgeRunError):
        runner.evaluate(judge_input())
    assert runner.stats.failures == 1
    assert not cache_path.exists()


def test_retryable_provider_failure_uses_backoff(monkeypatch, tmp_path):
    waits = []
    monkeypatch.setattr("support_agent.judge.runner.time.sleep", waits.append)
    provider = FakeProvider(
        [ProviderError("temporary", status_code=429, retryable=True), valid_response()]
    )
    runner = JudgeRunner(provider, JudgeCache(tmp_path / "cache"), config())
    assert runner.evaluate(judge_input()).overall_pass
    assert runner.stats.retries == 1
    assert waits == [1]


def test_provider_retry_delay_and_error_sanitization():
    headers = Message()
    error = urllib.error.HTTPError("https://example.invalid", 429, "limited", headers, None)
    assert _retry_after_seconds(error, "Please try again in 3.8s") == 3.8
    sanitized = _sanitize_provider_message(
        "organization org_abc123; upgrade at https://provider.invalid/billing"
    )
    assert "org_abc123" not in sanitized
    assert "provider.invalid" not in sanitized
    provider_error = ProviderError("limited", retryable=True, retry_after_seconds=254.88)
    assert JudgeRunner._retry_wait(provider_error, 0) == 255.38
    assert _is_daily_token_quota_error("tokens per day (TPD): Limit 200000")
    assert not _is_daily_token_quota_error("tokens per minute (TPM): Limit 8000")


def test_experiment_namespaces_and_swapped_prompts_do_not_collide(tmp_path):
    provider = FakeProvider(
        [valid_response(), valid_response(), valid_pairwise_response(), valid_pairwise_response()]
    )
    cache = JudgeCache(tmp_path / "cache")
    runner = JudgeRunner(provider, cache, config())
    runner.evaluate(judge_input(), replicate="primary")
    runner.evaluate(judge_input(), replicate="repeat-2")
    base = {
        "case_id": "dev-1",
        "customer_context": "The app stops playing music.",
        "action_a": "AUTO_HANDLE",
        "reply_a": "Please restart the app.",
        "action_b": "ESCALATE",
        "reply_b": "A specialist should review this.",
        "evidence": [{"evidence_id": "train-1", "excerpt": "Please restart the app."}],
    }
    runner.evaluate_pair(base, order="first")
    swapped = {
        **base,
        "action_a": base["action_b"],
        "reply_a": base["reply_b"],
        "action_b": base["action_a"],
        "reply_b": base["reply_a"],
    }
    runner.evaluate_pair(swapped, order="swapped")
    assert len(list((tmp_path / "cache").glob("*.json"))) == 4
    assert len(provider.calls) == 4


def test_stable_sampling_oversamples_every_auto_handle():
    predictions = []
    thread_map = {}
    for index in range(12):
        case_id = f"dev-{index}"
        predictions.append(
            {
                "case_id": case_id,
                "action": "AUTO_HANDLE" if index < 3 else "ESCALATE",
                "intent": "playback_or_app_behavior" if index % 2 else "other_or_unclear",
                "evidence_sufficient": index % 3 == 0,
                "risk_tags": [] if index % 4 else ["LOW_CONTEXT"],
            }
        )
        thread_map[case_id] = support_thread(case_id)
    first = build_development_sample(predictions, thread_map, sample_size=8, seed="seed")
    second = build_development_sample(predictions, thread_map, sample_size=8, seed="seed")
    assert first == second
    selected = {item["case_id"] for item in first}
    assert {"dev-0", "dev-1", "dev-2"} <= selected


def test_frozen_ids_rejected_and_provisional_truth_not_loaded(tmp_path):
    frozen = tmp_path / "frozen.json"
    frozen.write_text('{"thread_ids":["frozen-1"]}', encoding="utf-8")
    with pytest.raises(ValueError, match="frozen evaluation"):
        assert_no_frozen_thread_ids({"frozen-1"}, frozen, "judge")
    source = Path("scripts/run_judge.py").read_text(encoding="utf-8")
    assert "ai_provisional_labels" not in source


def test_secret_is_never_written_to_cache(tmp_path):
    provider = OpenAICompatibleProvider(
        api_key="secret-test-value",
        base_url="https://example.invalid/v1",
        model="test-model",
        temperature=0,
        timeout_seconds=1,
        reasoning_effort="low",
        max_completion_tokens=768,
        transport=lambda *_: {
            "choices": [{"message": {"content": valid_response()}}],
            "usage": {"total_tokens": 17},
        },
    )
    runner = JudgeRunner(provider, JudgeCache(tmp_path / "cache"), config())
    runner.evaluate(judge_input())
    cache_text = next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8")
    assert "secret-test-value" not in cache_text
