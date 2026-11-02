"""Regression coverage for Router output budgets, not upstream context lengths."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import BadRequestError, OpenAI
import pytest

from agent.router_output_budget import enforce_router_output_budget, record_router_result


def agent(model="openai/gpt-5.6-luna", provider="marcel"):
    value = SimpleNamespace(model=model, provider=provider, api_mode="chat_completions",
                            base_url="https://router.example/api/v1", max_tokens=None)
    value._max_tokens_param = lambda n: {
        "max_completion_tokens" if value.model.startswith("openai/gpt-5") else "max_tokens": n,
    }
    return value


@pytest.fixture(autouse=True)
def clean_config():
    with patch("marcel_cli.config.load_config", return_value={}):
        yield


@pytest.mark.parametrize("model,original,field", [
    ("openai/gpt-5.6-luna", {}, "max_completion_tokens"),
    ("anthropic/claude-sonnet-5", {"max_tokens": 128000}, "max_tokens"),
])
def test_default_budget_and_exact_serialized_integer(model, original, field):
    value = agent(model)
    kw = enforce_router_output_budget(value, {"model": model, "messages": [], **original}, final=True)
    captured = []

    def receive(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "fixture", "choices": [], "created": 1,
                                        "model": model, "object": "chat.completion"})

    with OpenAI(api_key="fake-unit-key", base_url=value.base_url,
                http_client=httpx.Client(transport=httpx.MockTransport(receive))) as client:
        client.chat.completions.create(**kw)
    assert captured[0][field] == 32768
    assert type(captured[0][field]) is int
    assert [key for key in captured[0] if key.startswith("max_")] == [field]


@pytest.mark.parametrize("invalid", [True, False, 0, -1, 10**5000, 1.5, 8192.0, float("nan"), float("inf"), "", "bad", "2e4", [], {}], ids=lambda value: type(value).__name__)
def test_invalid_values_become_valid_defaults_without_truncation(invalid):
    kw = enforce_router_output_budget(agent(), {"max_tokens": invalid})
    assert kw == {"max_completion_tokens": 32768}


def test_decimal_string_is_serialized_as_integer():
    assert enforce_router_output_budget(agent(), {"max_tokens": "12000"}) == {"max_completion_tokens": 12000}


def test_fallback_recomputes_model_limit_and_does_not_mutate_requested_budget():
    value = agent()
    value.max_tokens = 16000
    config = {"marcel": {"routing": {"model_entries": [
        {"id": value.model, "metadata": {"max_output_tokens": 4096}},
        {"id": "anthropic/claude-sonnet-5", "metadata": {"max_completion_tokens": 12000}},
    ]}}}
    with patch("marcel_cli.config.load_config", return_value=config):
        assert enforce_router_output_budget(value, {"max_completion_tokens": value.max_tokens}) == {"max_completion_tokens": 4096}
        value.model = "anthropic/claude-sonnet-5"
        assert enforce_router_output_budget(value, {"max_tokens": value.max_tokens}) == {"max_tokens": 12000}
    assert value.max_tokens == 16000


def test_extra_body_cannot_override_the_wire_budget():
    kw = enforce_router_output_budget(agent(), {
        "max_completion_tokens": 65536,
        "extra_body": {"max_tokens": "5000", "max_output_tokens": True, "keep": "yes"},
    })
    assert kw == {"max_completion_tokens": 5000, "extra_body": {"keep": "yes"}}


def test_configured_endpoint_scoping_and_unknown_upstream_limit():
    value = agent(provider="custom")
    config = {"marcel": {"router": {"mode": "marcel_router", "base_url": value.base_url},
                         "routing": {"model_entries": [{"id": value.model, "context_length": 1000000}]}}}
    with patch("marcel_cli.config.load_config", return_value=config):
        assert enforce_router_output_budget(value, {"max_tokens": 65536})["max_completion_tokens"] == 32768
        assert value._router_budget_selection["model_output_limit"] is None
        value.base_url = "https://different.example/api/v1"
        assert enforce_router_output_budget(value, {"max_tokens": 65536}) == {"max_tokens": 65536}
        assert value._router_client_request_id is None


def test_logs_link_wire_and_error_without_user_content_or_secrets(caplog):
    value = agent()
    with caplog.at_level(logging.INFO, logger="agent.router_output_budget"):
        kw = enforce_router_output_budget(value, {
            "messages": [{"role": "user", "content": "PRIVATE_USER_TEXT"}],
            "extra_headers": {"Authorization": "SECRET_HEADER"},
            "max_tokens": "SECRET_INVALID_BUDGET",
        }, final=True)
        record_router_result(value, error=SimpleNamespace(
            request_id="req-router-fixture", status_code=400, message="PRIVATE_ERROR_BODY",
        ))
    records = [json.loads(record.message.split("Router request ", 1)[1]) for record in caplog.records]
    assert records[0]["client_request_id"] == records[1]["client_request_id"] == kw["extra_headers"]["X-Client-Request-Id"]
    assert records[0]["serialized_value"] == 32768
    assert records[0]["serialized_type"] == "int"
    assert records[1]["router_request_id"] == "req-router-fixture"
    assert records[1]["http_status"] == 400
    assert all(record["timestamp_utc"].endswith("+00:00") and record["timezone"] for record in records)
    assert not any(secret in caplog.text for secret in (
        "PRIVATE_USER_TEXT", "SECRET_HEADER", "SECRET_INVALID_BUDGET", "PRIVATE_ERROR_BODY",
    ))


def test_sdk_response_header_is_linked_without_retaining_agent(caplog):
    class Owner:
        pass
    value = Owner()
    vars(value).update(vars(agent()))
    with OpenAI(api_key="fake-unit-key", base_url=value.base_url, http_client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"x-marcel-request-id": "router-header-fixture"},
            json={"id": "fixture", "choices": [], "created": 1, "model": value.model,
                  "object": "chat.completion"},
        )),
    )) as client, caplog.at_level(logging.INFO, logger="agent.router_output_budget"):
        value.client = client
        kwargs = enforce_router_output_budget(value, {"model": value.model, "messages": []}, final=True)
        response = client.chat.completions.create(**kwargs)
        record_router_result(value, response=response)
    assert value._router_response_metadata["router_request_id"] == "router-header-fixture"
    event = json.loads(caplog.records[-1].message.split("Router request ", 1)[1])
    assert event["router_request_id"] == "router-header-fixture" and event["http_status"] == 200


@pytest.mark.parametrize("mode,field", [("anthropic_messages", "max_tokens"), ("codex_responses", "max_output_tokens")])
def test_transport_parameter_translation(mode, field):
    value = agent()
    value.api_mode = mode
    assert enforce_router_output_budget(value, {"max_completion_tokens": 65536}) == {field: 32768}


def test_real_agent_rebuilds_budget_on_actual_fallback(tmp_path, monkeypatch):
    from run_agent import AIAgent
    from agent.chat_completion_helpers import build_api_kwargs
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    config = {"marcel": {"router": {"mode": "marcel_router", "base_url": "https://router.example/api/v1"},
                         "routing": {"model_entries": [
                             {"id": "openai/gpt-5.6-luna", "max_output_tokens": 4096},
                             {"id": "anthropic/claude-sonnet-5", "max_output_tokens": 12000},
                         ]}}}
    fallback = {"provider": "marcel", "model": "anthropic/claude-sonnet-5",
                "base_url": "https://router.example/api/v1", "api_key": "fake-unit-key",
                "api_mode": "chat_completions"}
    with patch("agent.model_metadata.get_model_context_length", return_value=128000), \
         patch("marcel_cli.config.load_config", return_value=config):
        value = AIAgent(
            model="openai/gpt-5.6-luna", provider="marcel",
            base_url="https://router.example/api/v1", api_key="fake-unit-key",
            api_mode="chat_completions", max_tokens=None, enabled_toolsets=[],
            quiet_mode=True, skip_memory=True, skip_context_files=True,
            skip_background_review=True, fallback_model=fallback,
        )
        try:
            assert value.max_tokens is None
            assert build_api_kwargs(value, [], [])["max_completion_tokens"] == 4096
            with OpenAI(api_key="fake-unit-key", base_url=fallback["base_url"]) as client, \
                 patch("agent.auxiliary_client.resolve_provider_client", return_value=(client, fallback["model"])):
                assert value._try_activate_fallback()
                kw = build_api_kwargs(value, [], [])
                assert kw["max_tokens"] == 12000
                assert "max_completion_tokens" not in kw
                assert value.model == fallback["model"]
                assert value.max_tokens is None
        finally:
            value.close()


def test_request_local_client_preserves_ids_even_when_exception_is_wrapped(tmp_path, monkeypatch, caplog):
    from run_agent import AIAgent
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    with patch("agent.model_metadata.get_model_context_length", return_value=128000):
        value = AIAgent(
            model="openai/gpt-5.6-luna", provider="marcel",
            base_url="https://router.example/api/v1", api_key="fake-unit-key",
            api_mode="chat_completions", enabled_toolsets=[], quiet_mode=True,
            skip_memory=True, skip_context_files=True, skip_background_review=True,
        )
    with OpenAI(api_key="fake-unit-key", base_url=value.base_url, http_client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            400, headers={"x-marcel-request-id": "request-local-fixture"},
            json={"error": {"message": "fixture failure", "type": "invalid_request_error"}},
        )),
    )) as wire_client, patch.object(value, "_create_openai_client", return_value=wire_client):
        try:
            kwargs = enforce_router_output_budget(value, {"model": value.model, "messages": []}, final=True)
            request_client = value._create_request_openai_client(reason="unit")
            with pytest.raises(BadRequestError):
                request_client.chat.completions.create(**kwargs)
            value._close_request_openai_client(request_client, reason="unit")
            assert value._create_request_openai_client(reason="unit-reuse") is wire_client
            value._close_request_openai_client(wire_client, reason="unit-reuse")
            with caplog.at_level(logging.INFO, logger="agent.router_output_budget"):
                record_router_result(value, error=RuntimeError("masked provider failure"))
            event = json.loads(caplog.records[-1].message.split("Router request ", 1)[1])
            assert event["router_request_id"] == "request-local-fixture"
            assert event["http_status"] == 400 and event["exception_type"] == "RuntimeError"
        finally:
            value.close()
