"""Regressions for relevant worker models and honest Router-only media setup."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from marcel_cli import config as config_module, setup, setup_marcel as wizard
from marcel_cli.setup_activity_models import compatible_models, recommendations
from marcel_cli.setup_media_status import media_worker_ready
from marcel_cli.setup_model_labels import LIVE_SETUP_CATALOG, validate_worker_models
from marcel_cli.setup_workers import configure_workers, print_worker_summary


def entry(model_id, *, caps=None, **meta):
    return {"id": model_id, "available": True, "metadata": {
        "capabilities": caps or {"chat": True, "tools": True}, **meta,
    }}


def catalog():
    return [
        entry("vendor/quality", quality_tier="high", cost_tier="high", speed_tier="low"),
        entry("vendor/balanced", quality_tier="medium", cost_tier="medium", speed_tier="medium"),
        entry("vendor/economy", quality_tier="low", cost_tier="low", speed_tier="high"),
        entry("vendor/vision", caps={"chat": True, "tools": True, "vision": True}),
        entry("vendor/video-reader", caps={"chat": True, "tools": True, "video_analysis": True}),
        entry("vendor/generator", caps={"image-generation": True}),
        {**entry("vendor/unavailable"), "available": False},
    ]


@pytest.fixture(autouse=True)
def isolate_catalog():
    token = LIVE_SETUP_CATALOG.set(None)
    yield
    LIVE_SETUP_CATALOG.reset(token)


def test_recommendations_are_small_distinct_and_explained_by_live_tiers():
    choices = recommendations(compatible_models(catalog(), "documents"), "documents")
    assert [item["id"] for _, item in choices] == [
        "vendor/quality", "vendor/balanced", "vendor/economy"]
    assert "Quality —" in choices[0][0] and "quality=high" in choices[0][0]
    assert "Quality/cost balance" in choices[1][0]
    assert "Speed/economy" in choices[2][0] and "speed=high" in choices[2][0]


def test_activity_metadata_can_update_recommendations_without_model_id_rules():
    entries = compatible_models(catalog(), "coding")
    entries[1]["metadata"]["recommended_for"] = ["coding"]
    choices = recommendations(entries, "coding")
    assert choices[0][1]["id"] == "vendor/balanced"
    assert "Router recommended_for=coding" in choices[0][0]
    assert recommendations([entry("unknown", quality_tier=["high"])], "coding") == []


@pytest.mark.parametrize("activity,expected", [
    ("vision", ["vendor/vision"]), ("video_analysis", ["vendor/video-reader"]),
])
def test_perception_primaries_and_fallbacks_require_explicit_input_support(activity, expected):
    LIVE_SETUP_CATALOG.set(catalog())
    ui = SimpleNamespace(_info=Mock(), print_error=Mock(),
                         prompt_choice=Mock(return_value=0))
    assert wizard._choose_model(ui, "Reasoning model", activity=activity) == expected[0]
    assert [model for _, model in wizard._fallback_catalog(activity)] == expected
    with pytest.raises(ValueError, match="activity capabilities"):
        validate_worker_models([{"activity": activity, "model": expected[0],
                                 "fallback_models": ["vendor/quality"]}], catalog())


def test_show_all_contains_only_compatible_models_and_never_a_generator():
    LIVE_SETUP_CATALOG.set(catalog())
    menus = []

    def choose(label, options, default=0):
        menus.append(list(options))
        return len(options) - 1 if len(menus) == 1 else 1

    ui = SimpleNamespace(_info=Mock(), print_error=Mock(), prompt_choice=choose)
    assert wizard._choose_model(ui, "Worker model", activity="coding") == "vendor/balanced"
    assert len(menus[0]) == 4  # Three recommendations followed by the full catalog.
    assert "Show all compatible" in menus[0][-1]
    assert not any("vendor/generator" in item or "vendor/unavailable" in item for item in menus[1])


def test_missing_perception_capability_does_not_fall_back_to_general_chat():
    LIVE_SETUP_CATALOG.set([entry("chat-only")])
    ui = SimpleNamespace(_info=Mock(), print_error=Mock(), prompt_choice=Mock())
    assert wizard._choose_model(ui, "Reader", activity="video_analysis") == ""
    ui.prompt_choice.assert_not_called()
    assert wizard._fallback_catalog("video_analysis") == []


@pytest.mark.parametrize("entries", [[], [entry("chat-only")]])
def test_explicit_catalog_never_falls_back_to_builtin_model_names(entries):
    ui = SimpleNamespace(_info=Mock(), print_error=Mock(), prompt_choice=Mock())
    assert wizard._choose_model(ui, "Video reader", activity="video_analysis",
                                live_models=entries) == ""
    assert wizard._fallback_catalog("video_analysis", live_models=entries) == []
    ui.prompt_choice.assert_not_called()


def test_native_video_and_vision_flags_survive_normalization_and_explicit_denials():
    raw = entry("native", supports_video_analysis=True, supports_vision=True)
    normalized = wizard._normalize_router_models({"data": [raw]})
    assert compatible_models(normalized, "vision")
    assert compatible_models(normalized, "video_analysis")
    raw["marcel"] = {"supports_video_analysis": False, "supports_vision": False}
    normalized = wizard._normalize_router_models({"data": [raw]})
    assert not compatible_models(normalized, "vision")
    assert not compatible_models(normalized, "video_analysis")


@pytest.mark.parametrize("activity,required,excluded", [
    ("search", {"web", "file"}, {"image_gen", "video_gen"}),
    ("coding", {"coding"}, {"image_gen", "video_gen"}),
    ("documents", {"file", "skills", "terminal"}, {"image_gen", "video_gen"}),
    ("video_analysis", {"video", "vision"}, {"video_gen"}),
    ("video", {"video_gen"}, {"video"}),
])
def test_activity_tools_separate_operational_roles(activity, required, excluded):
    ui = SimpleNamespace(_info=Mock(), prompt_checklist=lambda label, options, pre_selected: pre_selected)
    tools = set(wizard._choose_capabilities(ui, activity))
    assert required <= tools
    assert not excluded & tools


@pytest.mark.parametrize("activity,kind", [("image_generation", "image"), ("image", "image"), ("video", "video")])
@pytest.mark.parametrize("action", [0, 1])
def test_router_media_is_not_falsely_enabled_by_a_chat_model_or_catalog(activity, kind, action):
    config = {f"{kind}_gen": {"provider": "outside-router", "model": "existing-model"}}
    before = copy.deepcopy(config)
    ui = SimpleNamespace(_info=Mock(), print_error=Mock(),
                         prompt_choice=Mock(return_value=action))
    assert not media_worker_ready(ui, activity, config, router_only=True)
    assert config == before
    output = str(ui._info.call_args_list) + str(ui.print_error.call_args_list)
    assert f"Uses global {kind} service: outside-router / existing-model" in output
    assert "global service change affects every worker" in output
    assert "Cannot load the Router" in output
    assert "no worker was added" in output
    assert "separate from the media generator" in output


def test_router_media_worker_is_not_saved_and_never_requests_a_direct_key():
    additions = iter([True, False])
    prompts = []

    def choose(label, options, default=0):
        prompts.append(label)
        assert label in ("Sub-agent configuration", "Sub-agent activity",
                         "Global image generation service")
        return wizard.ACTIVITIES.index("image_generation") if label == "Sub-agent activity" else 0

    ui = SimpleNamespace(_info=Mock(), print_error=Mock(), prompt_choice=choose,
                         prompt_yes_no=lambda *a, **kw: next(additions),
                         prompt=lambda label: "Image worker")
    values = {"router_mode": "marcel_router", "workers": [], "live_model_entries": catalog()}
    configure_workers(ui, values, router_only=True)
    assert not values["workers"]
    assert not any("API key" in label for label in prompts)


def test_template_import_cannot_bypass_perception_eligibility(tmp_path):
    from marcel_cli.setup_workers import import_worker_template
    LIVE_SETUP_CATALOG.set(catalog())
    path = tmp_path / "worker.yaml"
    path.write_text("reader:\n  activity: video_analysis\n  model: vendor/quality\n  toolsets: [video]\n")
    with pytest.raises(ValueError, match="activity capabilities"):
        import_worker_template(str(path), [])


def test_router_media_template_import_is_atomic_and_cannot_enable_generation(tmp_path):
    LIVE_SETUP_CATALOG.set(catalog())
    path = tmp_path / "workers.yaml"
    path.write_text(
        "writer:\n  activity: documents\n  model: vendor/quality\n  toolsets: [file]\n"
        "painter:\n  activity: image_generation\n  model: vendor/quality\n  toolsets: [image_gen]\n"
    )
    additions = iter([True, False])
    ui = SimpleNamespace(
        _info=Mock(), print_error=Mock(),
        prompt_yes_no=lambda *a, **kw: next(additions),
        prompt=lambda label: str(path),
        prompt_choice=lambda label, options, default=0: 1 if label == "Sub-agent configuration" else 0,
    )
    values = {"workers": []}
    configure_workers(ui, values, router_only=True)
    assert values["workers"] == []
    assert "no workers were changed" in str(ui.print_error.call_args_list)


def test_video_generation_worker_serializes_global_engine_separately_from_llm():
    from tools.delegate_worker_registry import parse_workers
    worker = wizard.normalize_worker({
        "name": "Video", "activity": "video", "model": "vendor/chat",
        "toolsets": ["video_gen", "file"],
    })
    assert worker["model"] == "vendor/chat" and worker["video_service"] == "global"
    assert parse_workers({"video": worker})["video"]["video_service"] == "global"
    worker["video_service"] = "other"
    with pytest.raises(ValueError, match="video_service"):
        parse_workers({"video": worker})


def test_media_worker_summary_distinguishes_brain_from_shared_engine():
    ui = SimpleNamespace(_info=Mock())
    print_worker_summary(ui, {"id": "video", "activity": "video", "model": "vendor/chat"},
                         config={"video_gen": {"provider": "existing", "model": "video-model"}},
                         router_only=True)
    output = str(ui._info.call_args_list)
    assert "Reasoning/tool-use model: vendor/chat" in output
    assert "Uses global video service: existing / video-model" in output
    assert "not configured for this Router connection" in output


def test_document_worker_choices_roundtrip_without_touching_global_media(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    env = {}
    additions = iter([True, False])
    LIVE_SETUP_CATALOG.set(None)
    monkeypatch.setattr(setup, "get_env_value", lambda name: env.get(name))
    monkeypatch.setattr(setup, "save_env_value", lambda name, value: env.update({name: value}))
    monkeypatch.setattr(wizard, "_discover_marcel_router_models",
                        lambda *a: (True, "catalog ready", catalog()))

    def prompt(label, default="", password=False):
        if label == "Agent name":
            return "Test"
        if label == "Sub-agent name":
            return "Documents"
        if label == "Marcel Routing API key":
            return "test-only-router-key"
        return default

    def choose(label, options, default=0, **kwargs):
        assert label != "Connection"
        if label == "Sub-agent activity":
            return wizard.ACTIVITIES.index("documents")
        if label == "Sub-agent model for documents":
            return next(i for i, option in enumerate(options) if option.startswith("Quality/cost balance"))
        return default

    def checklist(label, options, pre_selected=None):
        return [] if "fallback" in label else list(pre_selected or [])

    monkeypatch.setattr(setup, "prompt", prompt)
    monkeypatch.setattr(setup, "prompt_choice", choose)
    monkeypatch.setattr(setup, "prompt_checklist", checklist)
    monkeypatch.setattr(setup, "prompt_yes_no",
                        lambda label, default=True: next(additions) if label == "Add a sub-agent?" else False)
    for name in ("ensure_marcel_soul", "ensure_marcel_welcome", "ensure_memory_maintenance_job"):
        monkeypatch.setattr(wizard, name, Mock())
    initial = {"image_gen": {"provider": "legacy", "model": "keep-me"}}
    wizard.setup_marcel(initial)
    saved = config_module.load_config()
    worker = saved["delegation"]["workers"]["documents"]
    assert worker["activity"] == "documents" and worker["model"] == "vendor/balanced"
    assert worker["provider"] == "marcel"
    assert {"file", "skills", "terminal"} <= set(worker["toolsets"])
    assert saved["image_gen"] == {"provider": "legacy", "model": "keep-me"}
    output = capsys.readouterr().out
    assert "reasoning/tool-use" in output and "Uses global image service" in output
    assert "test-only-router-key" not in output
