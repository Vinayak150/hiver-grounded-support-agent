"""OpenAI-compatible structured-output provider abstraction."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


class CredentialUnavailable(RuntimeError):
    """Raised before network access when the configured API credential is absent."""


class ProviderError(RuntimeError):
    """Sanitized provider failure that never contains credentials."""


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: dict[str, int] | None


Transport = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]


def _urllib_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ProviderError(f"Provider request failed: {type(error).__name__}") from error


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        timeout_seconds: float,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise CredentialUnavailable("Configured LLM API credential is unavailable.")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
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
        response = self._transport(
            f"{self.base_url}/chat/completions",
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
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
        transport=transport,
    )
