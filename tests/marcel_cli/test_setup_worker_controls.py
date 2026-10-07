"""Screen-level wizard contracts and credential-free template validation."""

import copy
import json
from unittest.mock import Mock

import pytest
import yaml

from marcel_cli import setup, setup_marcel as wizard
from marcel_cli.setup_model_labels import LIVE_SETUP_CATALOG, model_label
from marcel_cli.setup_workers import import_worker_template, configure_workers
from tools.delegate_worker_registry import WorkerConfigError


@pytest.fixture(autouse=True)
def isolate_catalog():
    token = LIVE_SETUP_CATALOG.set(None)
    yield
    LIVE_SETUP_CATALOG.reset(token)


def catalog():
    return [
        {"id": "marcel/reviewer", "alias_of": "provider/reviewer-2026",
         "provider": "Provider", "display_name": "Reviewer",
         "marcel": {"capabilities": {"chat": True, "tools": True}, "preview": True}},
        {"id": "provider/stable", "marcel": {"capabilities": {"chat": True, "tools": True}}},
        {"id": "provider/unavailable", "available": False,
         "marcel": {"capabilities": {"chat": True, "tools": True}}},
        {"id": "provider/images", "marcel": {"capabilities": {"image_generation": True}}},
        {"id": "provider/direct-only", "availability": "requires_direct_connection",
         "marcel": {"capabilities": {"chat": True, "tools": True}}},
    ]


def test_live_primary_and_fallback_screens_show_alias_preview_and_native_labels(capsys):
    LIVE_SETUP_CATALOG.set(catalog())
    seen = []

    def choose(title, options, default=0, **kwargs):
        print(title, *options, sep="\n")
        seen.append(options)
        return 0

    def checklist(title, options, **kwargs):
        print(title, *options, sep="\n")
        seen.append(options)
        return [0]

    ui = Mock(prompt_choice=choose, prompt_checklist=checklist)
    primary = wizard._choose_model(ui, "Sub-agent model")
    fallbacks = wizard._choose_fallback_models(ui, "image", primary)
    text = capsys.readouterr().out
    assert primary == "marcel/reviewer"
    assert fallbacks == ["provider/stable"]
    assert "canonical: provider/reviewer-2026" in text
    assert "Marcel alias" in text and "preview" in text
    assert "native provider ID" in text
    assert "available via Marcel Router" in text and "chat, tools" in text
    assert all("unavailable" not in choice and "images" not in choice and "direct-only" not in choice
               for options in seen for choice in options)
    assert "marcel/reviewer" not in "\n".join(seen[1])
    assert "unavailable for this account" in model_label(catalog()[2])
    assert "requires direct provider connection" in model_label(catalog()[4])


@pytest.mark.parametrize("raw", [
    {"w": {"model": "chat", "budget": {"max_requests": 0}}},
    {"w": {"model": "chat", "budget": {"max_cost_usd": float("nan")}}},
    {"w": {"model": "chat", "timeout_seconds": float("inf")}},
    {"w": {"model": "chat", "permissions": "selected"}},
    {"w": {"model": "chat", "toolsets": ["does-not-exist"]}},
    {"w": {"model": "chat", "secret": "never-print-this"}},
    {"w": {"model": "chat", "role": "bad-role"}},
    {"w": {"model": "chat", "typo": True}},
    [{"id": "w", "model": "chat"}, {"id": "w", "model": "chat"}],
])
def test_invalid_templates_are_rejected_without_echoing_contents(tmp_path, raw):
    path = tmp_path / "workers.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError) as exc:
        import_worker_template(str(path), [])
    assert "never-print-this" not in str(exc.value)


@pytest.mark.parametrize("text", [
    "w: {model: chat}\nw: {model: other}",
    "w: &worker {model: chat}\nother: *worker",
    "w: {model: chat, budget: {max_requests: 1, max_requests: 100}}",
    "w: [unclosed",
])
def test_duplicate_keys_aliases_and_bad_yaml_rejected(tmp_path, text):
    path = tmp_path / "workers.yaml"
    path.write_text(text)
    with pytest.raises(ValueError):
        import_worker_template(str(path), [])


def test_templates_validate_models_fallbacks_and_normalized_collisions(tmp_path):
    LIVE_SETUP_CATALOG.set(catalog())
    path = tmp_path / "workers.json"
    worker = {"activity": "coding", "model": "marcel/reviewer",
              "permissions": "selected", "toolsets": ["file"], "max_concurrency": 2,
              "budget": {"max_requests": 3}, "fallback_models": ["provider/stable"]}
    path.write_text(json.dumps({"Review": worker}))
    imported = import_worker_template(str(path), [])
    assert imported[0]["fallback_models"] == ["provider/stable"]
    with pytest.raises(WorkerConfigError):
        import_worker_template(str(path), [{"id": "review", **worker}])
    worker["fallback_models"] = ["provider/images"]
    path.write_text(json.dumps({"Review": worker}))
    with pytest.raises(ValueError, match="chat/tool"):
        import_worker_template(str(path), [])


def install_wizard_ui(monkeypatch, template=None):
    events = []
    saved = []
    additions = iter([True, False])

    def choose(label, options, default=0, **kwargs):
        events.append(label)
        print(label, *options, sep="\n")
        if label == "Connection":
            return 1
        if label == "Sub-agent configuration":
            return 1 if template else 0
        if label == "Sub-agent activity":
            return wizard.ACTIVITIES.index("coding")
        return default

    def prompt(label, default=None, password=False):
        events.append(label)
        if label == "Agent name":
            return "Owner"
        if label == "Sub-agent name":
            return "Reviewer"
        if label == "Worker template path":
            return str(template)
        if "Maximum API requests" in label:
            return "2"
        if "Maximum worker duration" in label:
            return "60"
        return default or ""

    def yes_no(label, default=False):
        events.append(label)
        if label == "Add a sub-agent?":
            return next(additions)
        return label == "Import these workers?"

    def checklist(label, options, pre_selected=None):
        events.append(label)
        return list(pre_selected or []) if "fallback" not in label else []

    monkeypatch.setattr(setup, "prompt_choice", choose)
    monkeypatch.setattr(setup, "prompt", prompt)
    monkeypatch.setattr(setup, "prompt_yes_no", yes_no)
    monkeypatch.setattr(setup, "prompt_checklist", checklist)
    monkeypatch.setattr(setup, "get_env_value", lambda key: "test-only-connection")
    monkeypatch.setattr(setup, "save_config", lambda config: saved.append(copy.deepcopy(config)))
    for name in ("_choose_image_provider", "_choose_voice_model", "ensure_marcel_soul",
                 "ensure_marcel_welcome", "ensure_memory_maintenance_job"):
        monkeypatch.setattr(wizard, name, lambda *args, **kwargs: None)
    monkeypatch.setattr("marcel_cli.setup_tts._setup_tts_provider", lambda *args, **kwargs: None)
    return events, saved


def test_full_wizard_screens_roundtrip_worker_limits_without_changing_main(monkeypatch, capsys, tmp_path):
    events, saved = install_wizard_ui(monkeypatch)
    config = {"approvals": {"mode": "smart"}, "delegation": {"max_iterations": 40}}
    wizard.setup_marcel(config)
    screen = capsys.readouterr().out
    assert screen.index("Main agent configured:") < screen.index("Sub-agent configuration")
    assert "Sub-agent permissions" in screen
    assert "max_requests=2" in screen and "max_duration_seconds=60" in screen
    assert "Permissions: selected" in screen and "Concurrency:" in screen
    assert "Main-agent autonomy is unchanged" in screen
    assert events.index("Sub-agent permissions") < next(i for i, label in enumerate(events) if "Maximum API" in label)
    assert saved[-1]["approvals"]["mode"] == "smart"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(saved[-1]))
    loaded = yaml.safe_load(path.read_text())
    worker = loaded["delegation"]["workers"]["reviewer"]
    assert worker["budget"] == {"max_requests": 2, "max_duration_seconds": 60}
    assert worker["permissions"] == "selected" and worker["max_concurrency"] > 0
    assert loaded["delegation"]["max_iterations"] == 40


def test_import_screen_summaries_and_save(monkeypatch, capsys, tmp_path):
    path = tmp_path / "workers.yaml"
    path.write_text(yaml.safe_dump({"writer": {
        "model": "provider/chat", "activity": "coding", "toolsets": ["file"],
        "permissions": "selected", "max_concurrency": 1, "budget": {"max_requests": 4},
    }}))
    events, saved = install_wizard_ui(monkeypatch, path)
    wizard.setup_marcel({})
    screen = capsys.readouterr().out
    assert "Import YAML/JSON worker template" in screen
    assert "Sub-agent configured: writer" in screen and "max_requests=4" in screen
    assert saved[-1]["delegation"]["workers"]["writer"]["permissions"] == "selected"
    assert "Sub-agent model for coding" not in events


def test_invalid_import_never_mutates_worker_values(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("unsafe: {model: chat, api_key: never-print-this}")
    values = {"workers": []}
    additions = iter([True, False])
    ui = Mock(prompt_yes_no=lambda *a, **kw: next(additions),
              prompt_choice=lambda *a, **kw: 1, prompt=lambda *a, **kw: str(path))
    configure_workers(ui, values)
    assert values["workers"] == []
    assert "never-print-this" not in str(ui.print_error.call_args)
