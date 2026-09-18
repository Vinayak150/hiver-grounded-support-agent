"""Cached execution for the isolated quota-safe Phase 5A V2 protocol."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

from .cache import JudgeCache
from .prompts_v2 import (
    ABSOLUTE_PREFIX,
    PAIRWISE_PREFIX,
    compact_absolute_messages,
    compact_pairwise_messages,
)
from .provider import ProviderError
from .runner import JudgeRunError
from .schema_v2 import (
    CompactJudgeResult,
    CompactPairwiseResult,
    compact_judge_schema,
    compact_pairwise_schema,
)


@dataclass
class V2RunStats:
    successful: int = 0
    retries: int = 0
    cache_hits: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    cached_input_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    pass_rule_corrections: int = 0


class V2JudgeRunner:
    def __init__(self, provider, cache: JudgeCache, config: dict[str, object]) -> None:
        self.provider = provider
        self.cache = cache
        self.config = config
        self.stats = V2RunStats()
        self.last_rate_limits: dict[str, str] = {}

    def _settings(self) -> dict[str, object]:
        return {
            "temperature": self.provider.temperature,
            "reasoning_effort": self.provider.reasoning_effort,
            "max_completion_tokens": self.provider.max_completion_tokens,
        }

    @staticmethod
    def _prompt_fingerprint(prefix: str, schema: dict[str, object]) -> str:
        encoded = prefix + json.dumps(schema, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _usage(self, usage: dict[str, int] | None) -> None:
        if usage:
            for field in (
                "prompt_tokens",
                "cached_input_tokens",
                "completion_tokens",
                "total_tokens",
            ):
                setattr(self.stats, field, getattr(self.stats, field) + usage.get(field, 0))

    @staticmethod
    def _retry_wait(error: ProviderError, attempt: int) -> float:
        return min(max(float(2**attempt), (error.retry_after_seconds or 0.0) + 0.5), 600.0)

    def _cached(self, key: str, result_type):
        cached = self.cache.get(key)
        if cached is None:
            return None
        self.stats.cache_hits += 1
        self._usage(cached.get("usage"))
        self.stats.retries += int(cached.get("retry_count", 0))
        self.stats.pass_rule_corrections += int(cached.get("pass_rule_corrected", False))
        return result_type.from_json(str(cached["response_json"]))

    def evaluate(
        self,
        *,
        case_id: str,
        customer: str,
        reply: str,
        action: str,
        evidence: tuple[str, ...],
        replicate: str = "primary",
    ) -> CompactJudgeResult:
        item = {
            "case_id": case_id,
            "customer": customer,
            "reply": reply,
            "action": action,
            "evidence": list(evidence),
        }
        key = self.cache.key(
            {
                "protocol": self.config["version"],
                "model": self.provider.model,
                "rubric_version": self.config["rubric_version"],
                "prompt_version": self.config["prompt_version"],
                "prompt_fingerprint": self._prompt_fingerprint(
                    ABSOLUTE_PREFIX, compact_judge_schema()
                ),
                "input": item,
                "experiment_namespace": replicate,
                **self._settings(),
            }
        )
        cached = self._cached(key, CompactJudgeResult)
        if cached is not None:
            return cached
        messages = compact_absolute_messages(
            customer=customer, reply=reply, action=action, evidence=evidence
        )
        errors = []
        for attempt in range(int(self.config["max_retries"]) + 1):
            if attempt:
                self.stats.retries += 1
            try:
                response = self.provider.complete(
                    messages, compact_judge_schema(), "support_judge_v2"
                )
                result = CompactJudgeResult.from_json(response.text)
                raw_pass = json.loads(response.text).get("overall_pass")
                pass_rule_corrected = raw_pass != result.overall_pass
                self.cache.put(
                    key,
                    {
                        "response_json": response.text,
                        "usage": response.usage,
                        "rate_limits": response.rate_limits,
                        "retry_count": attempt,
                        "pass_rule_corrected": pass_rule_corrected,
                        "cache_key_version": "judge-v2-cache-v1",
                    },
                )
                self._usage(response.usage)
                self.stats.pass_rule_corrections += int(pass_rule_corrected)
                self.last_rate_limits = response.rate_limits or {}
                self.stats.successful += 1
                return result
            except (ProviderError, ValueError) as error:
                errors.append(f"{type(error).__name__}: {error}")
                if isinstance(error, ProviderError):
                    if not error.retryable:
                        break
                    if attempt < int(self.config["max_retries"]):
                        time.sleep(self._retry_wait(error, attempt))
        self.stats.failures += 1
        raise JudgeRunError(f"V2 judge failed after bounded retries: {','.join(errors)}")

    def evaluate_pair(
        self,
        *,
        case_id: str,
        customer: str,
        action_a: str,
        reply_a: str,
        action_b: str,
        reply_b: str,
        evidence: tuple[str, ...],
        order: str,
    ) -> CompactPairwiseResult:
        item = {
            "case_id": case_id,
            "customer": customer,
            "action_a": action_a,
            "reply_a": reply_a,
            "action_b": action_b,
            "reply_b": reply_b,
            "evidence": list(evidence),
        }
        key = self.cache.key(
            {
                "protocol": self.config["version"],
                "model": self.provider.model,
                "rubric_version": self.config["rubric_version"],
                "prompt_version": self.config["pairwise_prompt_version"],
                "prompt_fingerprint": self._prompt_fingerprint(
                    PAIRWISE_PREFIX, compact_pairwise_schema()
                ),
                "input": item,
                "experiment_namespace": f"order-bias-{order}",
                **self._settings(),
            }
        )
        cached = self._cached(key, CompactPairwiseResult)
        if cached is not None:
            return cached
        messages = compact_pairwise_messages(
            customer=customer,
            action_a=action_a,
            reply_a=reply_a,
            action_b=action_b,
            reply_b=reply_b,
            evidence=evidence,
        )
        errors = []
        for attempt in range(int(self.config["max_retries"]) + 1):
            if attempt:
                self.stats.retries += 1
            try:
                response = self.provider.complete(
                    messages, compact_pairwise_schema(), "support_pairwise_v2"
                )
                result = CompactPairwiseResult.from_json(response.text)
                self.cache.put(
                    key,
                    {
                        "response_json": response.text,
                        "usage": response.usage,
                        "rate_limits": response.rate_limits,
                        "retry_count": attempt,
                        "cache_key_version": "judge-v2-cache-v1",
                    },
                )
                self._usage(response.usage)
                self.last_rate_limits = response.rate_limits or {}
                self.stats.successful += 1
                return result
            except (ProviderError, ValueError) as error:
                errors.append(f"{type(error).__name__}: {error}")
                if isinstance(error, ProviderError):
                    if not error.retryable:
                        break
                    if attempt < int(self.config["max_retries"]):
                        time.sleep(self._retry_wait(error, attempt))
        self.stats.failures += 1
        raise JudgeRunError(f"V2 pairwise judge failed after bounded retries: {','.join(errors)}")
