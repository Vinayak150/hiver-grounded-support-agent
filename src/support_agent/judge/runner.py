"""Validated, retried and cached blinded judge execution."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .cache import JudgeCache
from .prompts import absolute_messages, pairwise_messages
from .provider import OpenAICompatibleProvider, ProviderError
from .schema import (
    JudgeInput,
    JudgeResult,
    PairwiseResult,
    judge_json_schema,
    pairwise_json_schema,
)


class JudgeRunError(RuntimeError):
    pass


@dataclass
class RunStats:
    successful: int = 0
    retries: int = 0
    cache_hits: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class JudgeRunner:
    def __init__(self, provider, cache: JudgeCache, config: dict[str, object]) -> None:
        self.provider: OpenAICompatibleProvider = provider
        self.cache = cache
        self.config = config
        self.stats = RunStats()

    def _usage(self, usage: dict[str, int] | None) -> None:
        if usage:
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                setattr(self.stats, field, getattr(self.stats, field) + usage.get(field, 0))

    def _cache_settings(self) -> dict[str, object]:
        return {
            "temperature": getattr(self.provider, "temperature", None),
            "reasoning_effort": getattr(self.provider, "reasoning_effort", None),
            "max_completion_tokens": getattr(self.provider, "max_completion_tokens", None),
        }

    @staticmethod
    def _retry_wait(error: ProviderError, attempt: int) -> float:
        provider_wait = error.retry_after_seconds or 0.0
        # A small margin avoids retrying on the provider's rolling-window boundary.
        return min(max(float(2**attempt), provider_wait + 0.5), 600.0)

    def evaluate(self, item: JudgeInput, *, replicate: str = "primary") -> JudgeResult:
        prompt_version = str(self.config["prompt_version"])
        key_payload = {
            "model": self.provider.model,
            "rubric_version": self.config["rubric_version"],
            "prompt_version": prompt_version,
            "input": item.as_dict(),
            "experiment_namespace": replicate,
            **self._cache_settings(),
        }
        key = self.cache.key(key_payload)
        cached = self.cache.get(key)
        if cached is not None:
            self.stats.cache_hits += 1
            self._usage(cached.get("usage"))
            self.stats.retries += int(cached.get("retry_count", 0))
            return JudgeResult.from_json(str(cached["response_json"]))
        messages = absolute_messages(
            item,
            model=self.provider.model,
            rubric_version=str(self.config["rubric_version"]),
            prompt_version=prompt_version,
        )
        errors = []
        for attempt in range(int(self.config["max_retries"]) + 1):
            if attempt:
                self.stats.retries += 1
            try:
                response = self.provider.complete(messages, judge_json_schema(), "support_judge")
                result = JudgeResult.from_json(response.text)
                if result.case_id != item.case_id:
                    raise ValueError("Judge case_id does not match input.")
                if result.judge_model != self.provider.model:
                    raise ValueError("Judge model metadata does not match configuration.")
                if result.rubric_version != self.config["rubric_version"]:
                    raise ValueError("Judge rubric metadata does not match configuration.")
                if result.prompt_version != prompt_version:
                    raise ValueError("Judge prompt metadata does not match configuration.")
                self.cache.put(
                    key,
                    {
                        "response_json": response.text,
                        "usage": response.usage,
                        "retry_count": attempt,
                        "cache_key_version": "judge-cache-v1",
                    },
                )
                self._usage(response.usage)
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
        raise JudgeRunError(f"Judge failed after bounded retries: {','.join(errors)}")

    def evaluate_pair(self, payload: dict[str, object], *, order: str) -> PairwiseResult:
        prompt_version = str(self.config["pairwise_prompt_version"])
        key_payload = {
            "model": self.provider.model,
            "rubric_version": self.config["rubric_version"],
            "prompt_version": prompt_version,
            "input": payload,
            "experiment_namespace": f"order-bias-{order}",
            **self._cache_settings(),
        }
        key = self.cache.key(key_payload)
        cached = self.cache.get(key)
        if cached is not None:
            self.stats.cache_hits += 1
            self._usage(cached.get("usage"))
            self.stats.retries += int(cached.get("retry_count", 0))
            return PairwiseResult.from_json(str(cached["response_json"]))
        messages = pairwise_messages(
            **payload,
            model=self.provider.model,
            rubric_version=str(self.config["rubric_version"]),
            prompt_version=prompt_version,
        )
        for attempt in range(int(self.config["max_retries"]) + 1):
            if attempt:
                self.stats.retries += 1
            try:
                response = self.provider.complete(
                    messages, pairwise_json_schema(), "support_pairwise_judge"
                )
                result = PairwiseResult.from_json(response.text)
                if result.case_id != payload["case_id"]:
                    raise ValueError("Pairwise case_id does not match input.")
                if (
                    result.judge_model != self.provider.model
                    or result.rubric_version != self.config["rubric_version"]
                    or result.prompt_version != prompt_version
                ):
                    raise ValueError("Pairwise judge metadata does not match configuration.")
                self.cache.put(
                    key,
                    {
                        "response_json": response.text,
                        "usage": response.usage,
                        "retry_count": attempt,
                    },
                )
                self._usage(response.usage)
                self.stats.successful += 1
                return result
            except (ProviderError, ValueError) as error:
                if isinstance(error, ProviderError):
                    if not error.retryable:
                        break
                    if attempt < int(self.config["max_retries"]):
                        time.sleep(self._retry_wait(error, attempt))
        self.stats.failures += 1
        raise JudgeRunError("Pairwise judge failed after bounded retries.")
