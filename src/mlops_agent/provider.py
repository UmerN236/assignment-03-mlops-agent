"""Selected free OpenRouter API, native structured calls, bounded/sanitized transport."""

import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import Field

from mlops_agent.config import Settings
from mlops_agent.tools import ToolInput


class ProviderUnavailable(Exception):
    """Only fixed, secret-safe messages may cross this boundary."""


class Function(ToolInput):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    arguments: str = Field(max_length=32768)


class Call(ToolInput):
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,200}$")
    type: str = Field(pattern="^function$")
    function: Function


@dataclass
class Turn:
    message: dict
    calls: list[Call]
    model: str
    cost: float | None


class OpenRouterProvider:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    def _request(self, method, path, payload=None):
        settings = self.settings
        if settings.llm_provider != "openrouter":
            raise ProviderUnavailable(
                "This adapter supports the selected OpenRouter provider only; "
                "Gemini has not been live-validated. No provider fallback was made"
            )
        if not settings.provider_ready():
            raise ProviderUnavailable("Missing OPENROUTER_API_KEY; live agent unavailable")
        # Recheck even if a caller modified the settings after construction.
        model = settings.llm_model or ""
        if model != "openrouter/free" and not re.fullmatch(r"[a-zA-Z0-9_./-]+:free", model):
            raise ProviderUnavailable("An explicitly free OpenRouter model is required")
        started = time.monotonic()
        try:
            with httpx.Client(
                base_url="https://openrouter.ai/api/v1/",
                headers={
                    "Authorization": "Bearer " + settings.openrouter_api_key.get_secret_value()
                },
                timeout=settings.llm_timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(method, path, json=payload) as response:
                    code = response.status_code
                    if code == 429:
                        raise ProviderUnavailable(
                            "Free provider quota/rate limit reached; retry later"
                        )
                    if code in {401, 403}:
                        raise ProviderUnavailable("Provider authentication/access rejected")
                    if code == 402:
                        raise ProviderUnavailable(
                            "Provider credits unavailable; no billing fallback"
                        )
                    if not 200 <= code < 300:
                        raise ProviderUnavailable(
                            "Configured free model/provider unavailable or request rejected"
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise ProviderUnavailable("Provider response exceeded size limit")
                        if time.monotonic() - started > settings.llm_timeout_seconds:
                            raise ProviderUnavailable("Provider response deadline exceeded")
                    value = json.loads(raw)
            if not isinstance(value, dict) or value.get("error"):
                raise ValueError
            return value
        except httpx.TimeoutException:
            raise ProviderUnavailable("Provider timed out; no automatic retry") from None
        except httpx.HTTPError:
            raise ProviderUnavailable("Provider network unavailable; no automatic retry") from None
        except (ValueError, TypeError):
            raise ProviderUnavailable("Provider returned an invalid response") from None

    def preflight(self) -> dict:
        """Actual key/model metadata, never credential values or arbitrary response text."""
        key = self._request("GET", "key").get("data", {})
        if not isinstance(key, dict) or key.get("is_free_tier") is not True:
            raise ProviderUnavailable("A verified free-tier OpenRouter account is required")
        models = self._request("GET", "models").get("data", [])
        if not isinstance(models, list):
            raise ProviderUnavailable("Provider model catalog unavailable")
        models = [m for m in models if isinstance(m, dict)]
        configured = self.settings.llm_model
        if configured != "openrouter/free":
            candidates = [m for m in models if m.get("id") == configured]
            try:
                supported = any(
                    "tools" in m.get("supported_parameters", [])
                    and Decimal(m["pricing"]["prompt"]) == 0
                    and Decimal(m["pricing"]["completion"]) == 0
                    for m in candidates
                )
            except (KeyError, InvalidOperation, TypeError):
                supported = False
            if not supported:
                raise ProviderUnavailable("Configured free model lacks verified free tool support")
        elif not any(m.get("id") == configured for m in models):
            raise ProviderUnavailable("Configured free router is absent from current model catalog")
        return {
            "provider": "openrouter",
            "requested_model": configured,
            "free_tier_verified": True,
            "catalog_model_verified": True,
            "free_router_filters_tool_support": configured == "openrouter/free",
        }

    def complete(self, messages, schemas) -> Turn:
        response = self._request(
            "POST",
            "chat/completions",
            {
                "model": self.settings.llm_model,
                "messages": messages,
                "tools": [{"type": "function", "function": schema} for schema in schemas],
                "tool_choice": "required",
                "max_tokens": 4096,
                "provider": {
                    "require_parameters": True,
                    "max_price": {"prompt": 0, "completion": 0, "request": 0},
                },
            },
        )
        try:
            choice = response["choices"][0]
            message = choice["message"]
            calls = [
                Call.model_validate({k: c[k] for k in ("id", "type", "function")})
                for c in message.get("tool_calls", [])
            ]
            if (
                choice.get("finish_reason") != "tool_calls"
                or not 1 <= len(calls) <= 8
                or len({c.id for c in calls}) != len(calls)
                or message.get("role") != "assistant"
            ):
                raise ValueError
            model = response["model"]
            if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9_./:-]{1,200}", model):
                raise ValueError
            cost = response.get("usage", {}).get("cost")
            if cost is not None and (type(cost) not in {int, float} or cost != 0):
                raise ValueError
            # Preserve provider reasoning signatures internally for supported multi-turn calls.
            # They are never exported in the trace or logs.
            return Turn(message, calls, model, cost)
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            raise ProviderUnavailable(
                "Provider returned invalid/incomplete structured tool calls"
            ) from None
