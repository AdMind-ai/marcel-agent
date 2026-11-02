"""Router service wire contracts, isolation, files and wizard persistence."""
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from agent.router_services import RouterServiceError, RouterServices, service_models
from plugins.image_gen.marcel import MarcelImageProvider
from plugins.video_gen.marcel import MarcelVideoProvider
from plugins.web.marcel import MarcelSearchProvider


PNG = b"\x89PNG\r\n\x1a\nunit-test-image"
MP4 = b"\x00\x00\x00\x18ftypisomunit-test-video"
VIDEO = {"id": "vendor/video", "metadata": {
    "capabilities": ["video-generation"], "durations": [8], "resolutions": ["720p"],
    "aspect_ratios": ["16:9"], "valid_combinations": [{"duration_seconds": 8, "resolution": "720p"}],
}}


def response(data=None, *, status=200, content=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = content if content is not None else json.dumps(data).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def configured(monkeypatch, tmp_path):
    config = {
        "marcel": {"router": {"mode": "marcel_router", "base_url": "https://router.example/api/v1",
                              "key_env": "TEST_ROUTER_KEY"}},
        "image_gen": {"provider": "marcel", "model": "vendor/image"},
        "video_gen": {"provider": "marcel", "model": "vendor/video"},
    }
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    monkeypatch.setattr("marcel_cli.config.load_config", lambda: config)
    monkeypatch.setattr("agent.secret_scope.get_secret", lambda name: "test-key" if name == "TEST_ROUTER_KEY" else "")
    return config


def test_only_explicit_generators_are_selectable():
    rows = [
        {"id": "image", "metadata": {"capabilities": ["image-generation"]}},
        {"id": "vision", "metadata": {"capabilities": ["vision", "chat"]}},
        {"id": "offline", "available": False, "capabilities": {"image_generation": True}},
        {"id": "video", "metadata": {"capabilities": ["video-generation"]}},
    ]
    assert [row["id"] for row in service_models(rows, "image")] == ["image"]
    assert [row["id"] for row in service_models(rows, "video")] == ["video"]


@pytest.mark.parametrize("url", [
    "http://external.example/api/v1", "https://user:password@router.example/api/v1",
    "https://router.example/api/v1?key=secret", "file:///tmp/router",
])
def test_credentials_are_not_read_for_unsafe_endpoints(configured, url):
    configured["marcel"]["router"]["base_url"] = url
    getter = Mock(return_value="test-key")
    with pytest.raises(RouterServiceError):
        RouterServices(configured, getter)
    getter.assert_not_called()


def test_requests_are_scoped_and_do_not_follow_credential_redirects(configured, monkeypatch):
    transport = Mock(return_value=response({}, status=302, headers={"Location": "https://other.example"}))
    monkeypatch.setattr(requests, "request", transport)
    with pytest.raises(RouterServiceError, match="HTTP 302"):
        RouterServices().request("GET", "/models")
    args, kwargs = transport.call_args
    assert args == ("GET", "https://router.example/api/v1/models")
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"] == {"Authorization": "Bearer test-key"}
    assert transport.call_count == 1


def test_bound_router_key_is_not_read_after_origin_changes(configured):
    getter = Mock(return_value="https://old-router.example")
    with pytest.raises(RouterServiceError, match="origin changed"):
        RouterServices(configured, getter)
    getter.assert_called_once_with("TEST_ROUTER_KEY_ORIGIN")


def test_provider_errors_do_not_expose_response_contents(configured, monkeypatch):
    monkeypatch.setattr(requests, "request", Mock(return_value=response(
        {"error": "sensitive-provider-content"}, status=402, headers={"x-marcel-request-id": "req-123"},
    )))
    result = MarcelImageProvider().generate("fixture")
    assert result["success"] is False
    assert "req-123" in result["error"]
    assert "sensitive-provider-content" not in json.dumps(result)


def test_image_generation_posts_once_and_saves_file(configured, monkeypatch):
    transport = Mock(return_value=response({"data": [{"b64_json": base64.b64encode(PNG).decode()}]}))
    monkeypatch.setattr(requests, "request", transport)
    result = MarcelImageProvider().generate("fixture", aspect_ratio="portrait")
    assert result["success"]
    assert Path(result["image"]).read_bytes() == PNG
    payload = transport.call_args.kwargs["json"]
    assert payload == {"model": "vendor/image", "prompt": "fixture", "n": 1, "size": "1024x1536",
                       "quality": "medium", "response_format": "b64_json"}
    assert transport.call_args.kwargs["headers"]["Idempotency-Key"]
    assert transport.call_count == 1


def test_image_editing_is_rejected_before_paid_request(configured, monkeypatch):
    transport = Mock()
    monkeypatch.setattr(requests, "request", transport)
    assert MarcelImageProvider().generate("fixture", image_url="https://example.org/a.png")["error_type"] == "unsupported_modality"
    transport.assert_not_called()


@pytest.mark.parametrize("source", ["brave", "exa", "tavily", "perplexity"])
def test_search_uses_router_and_normalizes_results(configured, monkeypatch, source):
    rows = [
        {"title": "Title", "url": "https://example.org", "snippet": "Snippet"},
    ]
    data = {"web": {"results": rows}} if source == "brave" else {"results": rows}
    transport = Mock(return_value=response({"provider": source, "data": data}))
    monkeypatch.setattr(requests, "request", transport)
    result = MarcelSearchProvider(source).search("fixture", 1)
    assert result == {"success": True, "data": {"web": [{
        "title": "Title", "url": "https://example.org", "description": "Snippet", "position": 1,
    }]}}
    assert transport.call_args.args[1] == "https://router.example/api/v1/tools/search"
    assert transport.call_args.kwargs["json"] == {"provider": source, "query": "fixture", "max_results": 1}


def test_video_submits_polls_downloads_and_saves_mp4(configured, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"video_models": [VIDEO]})))
    transport = Mock(side_effect=[response({"id": "job-1"}), response({"status": "completed"}),
                                  response(content=MP4)])
    monkeypatch.setattr(requests, "request", transport)
    result = MarcelVideoProvider().generate("fixture", duration=8)
    assert result["success"]
    assert Path(result["video"]).read_bytes() == MP4
    assert [call.args[0] for call in transport.call_args_list] == ["POST", "GET", "GET"]
    assert transport.call_args_list[0].kwargs["headers"]["Idempotency-Key"]
    assert "headers" not in requests.get.call_args.kwargs


def test_resume_video_does_not_submit_another_paid_job(configured, monkeypatch):
    transport = Mock(side_effect=[response({"status": "completed"}), response(content=MP4)])
    monkeypatch.setattr(requests, "request", transport)
    result = MarcelVideoProvider().generate("fixture", job_id="existing-job")
    assert result["success"]
    assert all(call.args[0] == "GET" for call in transport.call_args_list)


def test_unsupported_video_parameters_are_rejected_before_submission(configured, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"video_models": [VIDEO]})))
    transport = Mock()
    monkeypatch.setattr(requests, "request", transport)
    assert MarcelVideoProvider().generate("fixture", duration=60)["error_type"] == "invalid_request"
    transport.assert_not_called()


def test_pending_video_preserves_job_id(configured, monkeypatch):
    transport = Mock(return_value=response({"status": "in_progress"}))
    monkeypatch.setattr(requests, "request", transport)
    monkeypatch.setattr("plugins.video_gen.marcel.time.monotonic", Mock(side_effect=[0, 0, 181]))
    monkeypatch.setattr("plugins.video_gen.marcel.time.sleep", lambda _: None)
    result = MarcelVideoProvider().generate("fixture", job_id="existing-job")
    assert result["error_type"] == "job_pending"
    assert result["job_id"] == "existing-job"
    assert all(call.args[0] == "GET" for call in transport.call_args_list)


def test_wizard_configures_media_without_using_generator_as_llm(configured, monkeypatch):
    from marcel_cli.setup_media_status import media_worker_ready
    monkeypatch.setattr(RouterServices, "models", lambda self, kind: [{"id": "vendor/new-image"}])
    ui = SimpleNamespace(_info=Mock(), print_error=Mock(), prompt_choice=Mock(return_value=0),
                         get_env_value=lambda key: "https://router.example" if key.endswith("_ORIGIN") else "test-key")
    assert media_worker_ready(ui, "image_generation", configured, router_only=True)
    assert configured["image_gen"] == {"provider": "marcel", "model": "vendor/new-image"}
    assert ui.prompt_choice.call_args.args[0] == "Router image generation model"
    ui.print_error.assert_not_called()


def test_wizard_search_is_a_service_not_an_llm_model(configured, monkeypatch):
    from marcel_cli.setup_media_status import configure_router_search
    monkeypatch.setattr(RouterServices, "search_providers", lambda self: ["brave", "exa", "tavily"])
    ui = SimpleNamespace(_info=Mock(), print_error=Mock(), prompt_choice=Mock(return_value=1),
                         get_env_value=lambda key: "https://router.example" if key.endswith("_ORIGIN") else "test-key")
    assert configure_router_search(ui, configured, required=True)
    assert configured["web"] == {"backend": "marcel-exa", "search_backend": "marcel-exa"}


def test_image_worker_creation_keeps_brain_and_generator_separate(configured, monkeypatch):
    from marcel_cli import setup_marcel as wizard
    from marcel_cli.setup_model_labels import LIVE_SETUP_CATALOG
    from marcel_cli.setup_workers import configure_workers
    brain = {"id": "vendor/brain", "metadata": {
        "capabilities": ["chat", "coding", "vision"], "supports_tool_calls": True,
    }}
    values = {"workers": [], "router_mode": "marcel_router", "live_model_entries": [brain]}
    monkeypatch.setattr(RouterServices, "models", lambda self, kind: [{"id": "vendor/new-image"}])
    monkeypatch.setattr(wizard, "_choose_model", lambda *a, **k: "vendor/brain")
    monkeypatch.setattr(wizard, "_choose_fallback_models", lambda *a, **k: [])
    monkeypatch.setattr(wizard, "_choose_capabilities", lambda *a: ["image_gen"])
    monkeypatch.setattr(wizard, "_choose_concurrency", lambda *a: 1)
    monkeypatch.setattr("marcel_cli.setup_workers.choose_worker_limits", lambda *a: {"permissions": "selected"})
    add_worker = iter([True, False])
    ui = SimpleNamespace(
        _info=Mock(), print_error=Mock(), prompt=Mock(return_value="Painter"),
        prompt_yes_no=lambda *a, **k: next(add_worker),
        prompt_choice=lambda label, *a, **k: wizard.ACTIVITIES.index("image_generation") if label == "Sub-agent activity" else 0,
        get_env_value=lambda key: "https://router.example" if key.endswith("_ORIGIN") else "test-key",
    )
    token = LIVE_SETUP_CATALOG.set([brain])
    try:
        configure_workers(ui, values, router_only=True, config=configured)
    finally:
        LIVE_SETUP_CATALOG.reset(token)
    ui.print_error.assert_not_called()
    assert len(values["workers"]) == 1
    assert values["workers"][0]["model"] == "vendor/brain"
    assert configured["image_gen"] == {"provider": "marcel", "model": "vendor/new-image"}
