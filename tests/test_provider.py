"""Supported OpenRouter wire protocol and failure handling with safe mock transport."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from mlops_agent.config import Settings
from mlops_agent.provider import OpenRouterProvider, ProviderUnavailable


def provider(handler, **kwargs):
    return OpenRouterProvider(
        Settings(openrouter_api_key="unit-test-secret", **kwargs),
        transport=httpx.MockTransport(handler),
    )


def response(calls=None, **extra):
    return {
        "model": "mock/model:free",
        "usage": {"cost": 0},
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": calls
                    or [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "read_health", "arguments": "{}"},
                        }
                    ],
                },
            }
        ],
        **extra,
    }


def test_native_tool_wire_free_price_cap_signatures_and_no_model_fallback():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "openrouter/free"
        assert "models" not in body
        assert body["provider"] == {
            "require_parameters": True,
            "max_price": {"prompt": 0, "completion": 0, "request": 0},
        }
        assert body["tool_choice"] == "required"
        assert body["tools"][0]["function"]["name"] == "read_health"
        raw = response()
        raw["choices"][0]["message"]["tool_calls"][0]["index"] = 0
        raw["choices"][0]["message"]["reasoning_details"] = [{"signature": "opaque"}]
        return httpx.Response(200, json=raw)

    turn = provider(handler).complete(
        [], [{"name": "read_health", "parameters": {"type": "object"}}]
    )
    assert turn.calls[0].function.name == "read_health"
    assert turn.message["reasoning_details"][0]["signature"] == "opaque"
    assert turn.cost == 0


@pytest.mark.parametrize("code", [401, 402, 403, 404, 429, 500, 503])
def test_errors_are_sanitized_not_retried_and_never_fallback(code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(code, json={"error": {"message": "unit-test-secret"}})

    with pytest.raises(ProviderUnavailable) as error:
        provider(handler).complete([], [])
    assert "unit-test-secret" not in str(error.value)
    assert len(requests) == 1


def test_provider_timeout_sanitized_and_not_retried():
    def handler(request):
        raise httpx.ReadTimeout("unit-test-secret")

    with pytest.raises(ProviderUnavailable, match="timed out"):
        provider(handler).complete([], [])


def test_provider_deadline_checked_even_when_stream_keeps_responding(monkeypatch):
    monkeypatch.setattr(
        "mlops_agent.provider.time",
        SimpleNamespace(monotonic=Mock(side_effect=[0, 61])),
    )
    handler = Mock(return_value=httpx.Response(200, json=response()))
    with pytest.raises(ProviderUnavailable, match="deadline"):
        provider(handler).complete([], [])
    handler.assert_called_once()


def test_provider_oversized_response_rejected_before_becoming_evidence():
    handler = Mock(return_value=httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)))
    with pytest.raises(ProviderUnavailable, match="size limit"):
        provider(handler).complete([], [])
    handler.assert_called_once()


@pytest.mark.parametrize(
    "raw",
    [
        {"error": {"message": "unit-test-secret"}},
        {"choices": []},
        response(usage={"cost": 0.2}),
        response(usage={"cost": "unit-test-secret"}),
        response(
            calls=[
                {"id": "c", "type": "function", "function": {"name": "bad name", "arguments": "{}"}}
            ]
        ),
    ],
)
def test_invalid_protocol_or_unexpected_cost_rejected(raw):
    with pytest.raises(ProviderUnavailable) as error:
        provider(lambda r: httpx.Response(200, json=raw)).complete([], [])
    assert "unit-test-secret" not in str(error.value)


def test_non_tool_finish_and_truncated_call_rejected():
    raw = response()
    raw["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ProviderUnavailable):
        provider(lambda r: httpx.Response(200, json=raw)).complete([], [])


def test_free_tier_catalog_preflight():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        value = (
            {"data": {"is_free_tier": True}}
            if request.url.path.endswith("/key")
            else {"data": [{"id": "openrouter/free"}]}
        )
        return httpx.Response(200, json=value)

    result = provider(handler).preflight()
    assert result["free_tier_verified"] is True
    assert len(seen) == 2


def test_model_absent_from_catalog_prevents_inference():
    def handler(request):
        return httpx.Response(
            200, json={"data": {"is_free_tier": True} if request.url.path.endswith("/key") else []}
        )

    with pytest.raises(ProviderUnavailable, match="absent"):
        provider(handler).preflight()


def test_paid_account_or_unsupported_provider_fails_closed():
    with pytest.raises(ProviderUnavailable, match="free-tier"):
        provider(lambda r: httpx.Response(200, json={"data": {"is_free_tier": False}})).preflight()
    with pytest.raises(ProviderUnavailable, match="OpenRouter provider only"):
        provider(
            lambda r: pytest.fail("No fallback"),
            llm_provider="gemini",
            gemini_model="user-selected",
            gemini_api_key="test",
        ).preflight()
