"""OpenAI-compatible structured-output provider abstraction."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


class CredentialUnavailable(RuntimeError):
    """Raised before network access when the configured API credential is absent."""


class ProviderError(RuntimeError):
    """Sanitized provider failure that never contains credentials."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: dict[str, int] | None


Transport = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]


def _sanitize_provider_message(message: str) -> str:
    """Keep actionable provider detail while removing tenant IDs and URLs."""
    message = re.sub(r"\borg_[A-Za-z0-9_-]+\b", "<organization>", message)
    return re.sub(r"https?://\S+", "<provider-url>", message)


def _is_daily_token_quota_error(message: str) -> bool:
    return bool(re.search(r"tokens per day|\bTPD\b", message, re.I))


def _retry_after_seconds(error: urllib.error.HTTPError, message: str) -> float | None:
    header = error.headers.get("Retry-After") if error.headers else None
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    match = re.search(r"try again in\s+([0-9]*\.?[0-9]+)\s*(ms|s|m)\b", message, re.I)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).casefold()
    if unit == "ms":
        return value / 1000
    if unit == "m":
        return value * 60
    return value


def _urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        response_message = ""
        try:
            payload = json.loads(error.read().decode("utf-8"))
            detail = payload.get("error", {})
            if isinstance(detail, dict):
                response_message = str(detail.get("message", ""))[:500]
        except (json.JSONDecodeError, UnicodeDecodeError):
            response_message = ""
        retry_after = _retry_after_seconds(error, response_message)
        daily_token_quota = _is_daily_token_quota_error(response_message)
        response_message = _sanitize_provider_message(response_message)
        suffix = f": {response_message}" if response_message else ""
        raise ProviderError(
            f"Provider HTTP {error.code}{suffix}",
            status_code=error.code,
            retryable=(error.code == 429 and not daily_token_quota) or error.code >= 500,
            retry_after_seconds=retry_after,
        ) from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ProviderError(
            f"Provider request failed: {type(error).__name__}", retryable=True
        ) from error


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        timeout_seconds: float,
        reasoning_effort: str | None = None,
        max_completion_tokens: int | None = None,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise CredentialUnavailable("Configured LLM API credential is unavailable.")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.max_completion_tokens = max_completion_tokens
        self._transport = transport or _urllib_transport

    def complete(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
    ) -> ProviderResponse:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.max_completion_tokens is not None:
            payload["max_completion_tokens"] = self.max_completion_tokens
        response = self._transport(
            f"{self.base_url}/chat/completions",
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "hiver-grounded-support-agent/phase5a",
            },
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            self.timeout_seconds,
        )
        try:
            text = str(response["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("Provider response omitted structured message content.") from error
        raw_usage = response.get("usage")
        usage = None
        if isinstance(raw_usage, dict):
            usage = {
                key: int(raw_usage[key])
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(raw_usage.get(key), int)
            }
        return ProviderResponse(text=text, usage=usage)


def provider_from_environment(
    config: dict[str, object], transport: Transport | None = None
) -> OpenAICompatibleProvider:
    provider_name = str(config["provider"])
    providers = config["providers"]
    if provider_name not in providers:
        raise ValueError(f"Unsupported provider: {provider_name}")
    settings = providers[provider_name]
    key_name = str(settings["api_key_env"])
    api_key = os.environ.get(key_name, "")
    if not api_key:
        raise CredentialUnavailable(f"{key_name} is not configured; real LLM judging cannot run.")
    base_url = os.environ.get(str(settings["base_url_env"]), str(settings["default_base_url"]))
    model = os.environ.get(f"{provider_name.upper()}_MODEL", str(config["model"]))
    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=float(config["temperature"]),
        timeout_seconds=float(config["timeout_seconds"]),
        reasoning_effort=(
            str(config["reasoning_effort"]) if config.get("reasoning_effort") is not None else None
        ),
        max_completion_tokens=(
            int(config["max_completion_tokens"])
            if config.get("max_completion_tokens") is not None
            else None
        ),
        transport=transport,
    )
