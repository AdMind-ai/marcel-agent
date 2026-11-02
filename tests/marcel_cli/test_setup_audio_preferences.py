from types import SimpleNamespace
from unittest.mock import Mock

from marcel_cli.setup_audio_preferences import configure_audio_preferences
from tools.transcription_tools import _resolve_stt_language


def test_preferred_italian_is_saved_and_resolved_by_runtime(tmp_path, monkeypatch):
    import yaml
    from marcel_cli.config import load_config
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    config = {"stt": {"provider": "openai", "openai": {"language": "en"}}, "display": {"tool_progress": True}}
    ui = SimpleNamespace(prompt_choice=Mock(return_value=1), prompt_yes_no=Mock(return_value=False),
                         _info=Mock(), print_error=Mock())
    assert configure_audio_preferences(ui, config)
    assert _resolve_stt_language("openai", config["stt"]) == "it"
    assert config["stt"]["echo_transcripts"] is False
    assert config["display"]["tool_progress"] is True
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
    restored = load_config()
    assert restored["stt"]["language"] == "it"
    assert restored["stt"]["echo_transcripts"] is False


def test_explicit_auto_does_not_forward_auto_as_a_language_code(monkeypatch):
    monkeypatch.setenv("MARCEL_LOCAL_STT_LANGUAGE", "en")
    assert _resolve_stt_language("openai", {"language": "auto"}) is None
    assert _resolve_stt_language("openai", {"language": "it"}) == "it"


def test_router_audio_wizard_settings_are_operational_and_survive_reload(tmp_path, monkeypatch):
    import yaml
    from unittest.mock import patch
    from marcel_cli.config import load_config
    from marcel_cli.setup_audio_preferences import configure_router_audio
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    cfg = {}
    # Model, Italian, native ASR, masculine voice, professional style, voice-to-voice.
    ui = SimpleNamespace(prompt_choice=Mock(side_effect=[0, 1, 0, 1, 2, 2]),
                         prompt_yes_no=Mock(side_effect=[True, False]), _info=Mock(), print_error=Mock())
    with patch("agent.router_services.RouterServices") as client, patch("marcel_cli.setup_audio_preferences.shutil.which", return_value="ffmpeg"):
        client.return_value.models.return_value = [{"id": "openai/gpt-realtime-2.1"}]
        assert configure_router_audio(ui, cfg)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    saved = load_config()
    assert saved["audio"]["recording_consent"] is True
    assert saved["audio"]["response_mode"] == "voice_to_voice"
    assert saved["voice"]["auto_tts"] is True
    assert saved["stt"]["provider"] == saved["tts"]["provider"] == "marcel"
    assert saved["stt"]["language"] == "it"
    assert saved["stt"]["echo_transcripts"] is False
    assert saved["tts"]["marcel"]["voice"] == "cedar"
    assert saved["tts"]["marcel"]["style"] == "professional"
    from agent.router_audio import RouterAudio
    assert RouterAudio(saved, Mock()).settings["audio_processing_consent"] is True


def test_declining_consent_disables_previous_audio_without_external_fallback():
    from unittest.mock import patch
    from marcel_cli.setup_audio_preferences import configure_router_audio
    cfg = {"audio": {"recording_consent": True, "audio_processing_consent": True},
           "stt": {"provider": "marcel", "enabled": True}}
    ui = SimpleNamespace(prompt_choice=Mock(return_value=0), prompt_yes_no=Mock(return_value=False),
                         _info=Mock(), print_error=Mock())
    with patch("agent.router_services.RouterServices") as client, patch("marcel_cli.setup_audio_preferences.shutil.which", return_value="ffmpeg"):
        client.return_value.models.return_value = [{"id": "openai/gpt-realtime-2.1"}]
        assert not configure_router_audio(ui, cfg)
    assert cfg["audio"]["recording_consent"] is False
    assert cfg["stt"]["enabled"] is False
    assert cfg["tts"]["provider"] == "marcel"
