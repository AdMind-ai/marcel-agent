"""Router-native metadata and launch onboarding regression coverage."""

import copy
import io
import json
from unittest.mock import Mock

import pytest

from marcel_cli import setup
from marcel_cli import setup_marcel as wizard
from marcel_cli.setup_model_labels import (
    LIVE_SETUP_CATALOG,
    catalog_summary,
    chat_models,
)


def native(model_id="vendor/chat", **overrides):
    return {"id": model_id, "metadata": {
        "capabilities": ["coding", "reasoning", "tools", "vision"],
        "supports_tool_calls": True,
    }, **overrides}


@pytest.fixture(autouse=True)
def isolate_catalog():
    token = LIVE_SETUP_CATALOG.set(None)
    yield
    LIVE_SETUP_CATALOG.reset(token)


@pytest.mark.parametrize("entry,eligible", [
    (native(), True),
    ({"id": "legacy", "capabilities": {"chat": True, "tools": True}}, True),
    ({"id": "legacy", "marcel": {"capabilities": ["chat", "tools"]}}, True),
    (native(metadata={"capabilities": ["coding", "tools"]}), False),
    (native(metadata={"capabilities": ["coding", "tools"], "supports_tool_calls": False}), False),
    (native(metadata={"capabilities": ["coding", "tools"], "supports_tool_calls": "true"}), False),
    (native(metadata={"capabilities": ["chat"]}), False),
    (native(metadata={"capabilities": ["image-generation"], "supports_tool_calls": True}), False),
    (native(metadata={"capabilities": ["embeddings"], "supports_tool_calls": True}), False),
    (native(metadata="invalid"), False),
    (native(metadata={"capabilities": [{"chat": True}], "supports_tool_calls": True}), False),
    (native(metadata={"capabilities": None, "supports_tool_calls": True}), False),
    (native(available=False), False),
    (native(availability="unavailable"), False),
    (native(marcel={"availability": "requires_direct_connection"}), False),
    (native(marcel={"supports_tool_calls": False}), False),
    (native(marcel={"capabilities": {"tools": False}}), False),
])
def test_native_and_legacy_contracts_fail_closed(entry, eligible):
    normalized = wizard._normalize_router_models({"data": [entry]})
    assert bool(chat_models(normalized)) is eligible


def test_normalization_and_saved_catalog_preserve_native_and_legacy_metadata():
    raw = native(marcel={"preview": True, "cost_tier": "low"})
    normalized = wizard._normalize_router_models({"data": [raw, raw, None, {"id": ["bad"]}]})
    assert len(normalized) == 1
    assert normalized[0]["metadata"]["supports_tool_calls"] is True
    assert normalized[0]["metadata"]["cost_tier"] == "low"
    values = {"agent_name": "Test", "router_mode": "marcel_router",
              "orchestrator_model": "vendor/chat", "live_model_entries": normalized}
    saved = wizard.build_marcel_config(values)["routing"]["model_entries"]
    assert chat_models(saved) == saved
    assert saved[0]["capabilities"]["vision"] is True
    assert saved[0]["preview"] is True


def test_catalog_summary_distinguishes_received_available_and_eligible():
    entries = wizard._normalize_router_models({"data": [
        native(), native("vendor/yes", available=True),
        native("vendor/no", available=False),
        native("vendor/direct", availability="requires_direct_connection"),
    ]})
    summary = catalog_summary(entries)
    assert "received: 4" in summary
    assert "Declared available: 1" in summary
    assert "unavailable/direct-only: 2" in summary
    assert "availability not declared: 1" in summary
    assert "Eligible orchestrator models: 2" in summary


@pytest.mark.parametrize("payload", [{"data": []}, {"data": "bad"}, {}, {"data": [None]}])
def test_empty_or_malformed_http_catalog_is_controlled(monkeypatch, payload):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    ok, message, entries = wizard._discover_marcel_router_models(
        wizard.MARCEL_ROUTER_BASE_URL, "test-only-key")
    assert not ok and not entries
    assert "catalogue" in message
    assert "test-only-key" not in message


def install_ui(monkeypatch, tmp_path, payloads, *, retry=False):
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    secret = "test-only-private-value"
    prompts, requests, saved = [], [], []
    responses = iter(payloads)
    env = {}
    monkeypatch.setattr(setup, "get_env_value", lambda name: env.get(name))
    monkeypatch.setattr(setup, "save_env_value", lambda name, value: env.update({name: value}))

    def http(request, **kwargs):
        requests.append(request.get_header("Authorization"))
        return io.BytesIO(json.dumps(next(responses)).encode())

    def prompt(label, default="", password=False):
        prompts.append(label)
        if "Routing API key" in label:
            assert password
            return secret
        return "Test" if label == "Agent name" else default

    def choose(label, options, default=0, **kwargs):
        prompts.append(label)
        assert label != "Connection"
        assert "image service" not in label.lower()
        return 0 if label in ("Orchestrator model", "Marcel Routing account") else default

    attempts = iter([retry, False])

    def yes_no(label, default=True):
        prompts.append(label)
        return next(attempts) if label == "Retry Marcel Router connection?" else False

    monkeypatch.setattr("urllib.request.urlopen", http)
    monkeypatch.setattr(setup, "prompt", prompt)
    monkeypatch.setattr(setup, "prompt_choice", choose)
    monkeypatch.setattr(setup, "prompt_yes_no", yes_no)
    monkeypatch.setattr(setup, "prompt_checklist",
                        lambda label, options, pre_selected=None: [])
    monkeypatch.setattr(setup, "save_config", lambda config: saved.append(copy.deepcopy(config)))
    for name in ("_choose_image_provider", "_choose_voice_model",
                 "ensure_marcel_soul", "ensure_marcel_welcome", "ensure_memory_maintenance_job"):
        monkeypatch.setattr(wizard, name, Mock())
    monkeypatch.setattr("marcel_cli.setup_tts._setup_tts_provider", Mock())
    return prompts, requests, saved, env, secret


def test_no_eligible_clean_exit_saves_key_without_config_or_traceback(monkeypatch, tmp_path, capsys):
    payload = {"data": [native(metadata={"capabilities": ["image-generation"]})]}
    prompts, requests, saved, env, secret = install_ui(monkeypatch, tmp_path, [payload])
    wizard.setup_marcel({})
    output = capsys.readouterr().out
    assert "No eligible orchestrator model" in output
    assert "Eligible orchestrator models: 0" in output
    assert secret not in output and "Traceback" not in output
    assert env["MARCEL_ROUTER_API_KEY"] == secret
    assert not saved
    assert "Orchestrator model" not in prompts
    assert requests == [f"Bearer {secret}"]
    assert LIVE_SETUP_CATALOG.get() is None


def test_retry_reuses_saved_key_and_router_only_setup_finishes(monkeypatch, tmp_path, capsys):
    bad = {"data": [native(metadata={"capabilities": ["chat"]})]}
    good = {"data": [native()]}
    prompts, requests, saved, env, secret = install_ui(
        monkeypatch, tmp_path, [bad, good], retry=True)
    wizard.setup_marcel({})
    assert prompts.count("Marcel Routing API key") == 1
    assert "Marcel Routing account" in prompts
    assert requests == [f"Bearer {secret}", f"Bearer {secret}"]
    assert saved[-1]["marcel"]["router"]["mode"] == "marcel_router"
    assert saved[-1]["marcel"]["orchestrator"]["model"] == "vendor/chat"
    assert chat_models(saved[-1]["marcel"]["routing"]["model_entries"])
    assert not wizard._choose_image_provider.called
    assert not wizard._choose_voice_model.called
    assert secret not in capsys.readouterr().out
    assert LIVE_SETUP_CATALOG.get() is None


def test_key_survives_clean_exit_and_next_invocation(monkeypatch, tmp_path, capsys):
    bad = {"data": [native(metadata={"capabilities": ["chat"]})]}
    prompts, requests, saved, env, secret = install_ui(
        monkeypatch, tmp_path, [bad, {"data": [native()]}])
    wizard.setup_marcel({})
    assert not saved
    assert env["MARCEL_ROUTER_API_KEY_ORIGIN"] == wizard._normalized_router_origin(
        wizard.MARCEL_ROUTER_BASE_URL)
    wizard.setup_marcel({})
    assert saved and prompts.count("Marcel Routing API key") == 1
    assert requests == [f"Bearer {secret}", f"Bearer {secret}"]
    assert secret not in capsys.readouterr().out


def test_retry_origin_change_never_sends_saved_key_without_consent(monkeypatch, tmp_path):
    bad = {"data": [native(metadata={"capabilities": ["chat"]})]}
    prompts, requests, saved, env, secret = install_ui(
        monkeypatch, tmp_path, [bad], retry=True)
    original = setup.prompt
    urls = iter([wizard.MARCEL_ROUTER_BASE_URL, "https://other.example/api/v1"])

    def prompt(label, default="", password=False):
        return next(urls) if label == "Marcel Router base URL" else original(
            label, default, password=password)

    monkeypatch.setattr(setup, "prompt", prompt)
    wizard.setup_marcel({})
    assert requests == [f"Bearer {secret}"]
    assert not saved
    assert any(label.startswith("Trust the new Router origin") for label in prompts)


def test_saved_key_with_no_completed_config_is_bound_to_origin(monkeypatch, tmp_path):
    prompts, requests, saved, env, secret = install_ui(monkeypatch, tmp_path, [])
    env.update(MARCEL_ROUTER_API_KEY=secret,
               MARCEL_ROUTER_API_KEY_ORIGIN="https://other.example")
    wizard.setup_marcel({})
    assert not requests and not saved
    assert any(label.startswith("Trust the new Router origin") for label in prompts)


def test_existing_direct_configuration_switches_without_reusing_its_key(monkeypatch, tmp_path):
    prompts, requests, saved, env, secret = install_ui(
        monkeypatch, tmp_path, [{"data": [native()]}])
    env["OPENAI_API_KEY"] = "direct-key-never-send-to-router"
    config = wizard.apply_marcel_config({}, {
        "agent_name": "Previous", "router_mode": "direct_provider",
        "direct_provider": "openai-api", "api_key_ref": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "orchestrator_model": "openai/previous", "workers": [], "accounts": [],
    })
    wizard.setup_marcel(config)
    assert requests == [f"Bearer {secret}"]
    assert "Connection" not in prompts
    assert saved[-1]["marcel"]["router"]["mode"] == "marcel_router"
