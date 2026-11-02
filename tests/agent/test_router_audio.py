import base64
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agent.router_audio import RouterAudio
from agent.router_services import RouterServiceError


def config():
    return {
        "audio": {"recording_consent": True, "audio_processing_consent": True, "response_mode": "on_request"},
        "stt": {"provider": "marcel", "language": "it", "marcel": {
            "model": "openai/gpt-realtime-2.1", "transcription_model": "gpt-live-transcribe"}},
        "tts": {"provider": "marcel", "marcel": {
            "model": "openai/gpt-realtime-2.1", "voice": "cedar", "style": "warm"}},
    }


class Socket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []

    def send(self, text):
        self.sent.append(json.loads(text))

    def recv(self, **kwargs):
        return json.dumps(next(self.events))


@pytest.mark.parametrize("language", [None, "it", "es"])
def test_stt_uses_final_transcription_only_and_language_hint(language):
    ws = Socket([{"type": "session.updated"},
                 {"type": "conversation.item.input_audio_transcription.delta", "delta": "partial"},
                 {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Ciao, sono qui."}])
    audio = RouterAudio(config(), Mock())
    converted = SimpleNamespace(returncode=0, stdout=b"\0" * 4800)
    with patch.object(audio, "connect", return_value=nullcontext(ws)), patch("agent.router_audio.shutil.which", return_value="ffmpeg"), patch("agent.router_audio.subprocess.run", return_value=converted):
        result = audio.transcribe("fixture.ogg", language=language)
    assert result["transcript"] == "Ciao, sono qui."
    input_settings = ws.sent[0]["session"]["audio"]["input"]
    assert input_settings["turn_detection"] is None
    if language:
        assert input_settings["transcription"]["language"] == language
    else:
        assert "language" not in input_settings["transcription"]
    assert ws.sent[-1]["type"] == "input_audio_buffer.commit"
    assert all(e["type"] != "response.create" for e in ws.sent)


def test_tts_applies_real_voice_style_and_saves_complete_wav(tmp_path):
    pcm = b"\0" * 4800
    ws = Socket([{"type": "session.updated"},
                 {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
                 {"type": "response.done", "response": {"status": "completed"}}])
    audio = RouterAudio(config(), Mock())
    with patch.object(audio, "connect", return_value=nullcontext(ws)):
        result = audio.synthesize("Ciao.", str(tmp_path / "reply.wav"))
    assert (tmp_path / "reply.wav").read_bytes().startswith(b"RIFF")
    assert result.endswith(".wav")
    session = ws.sent[0]["session"]
    assert session["audio"]["output"]["voice"] == "cedar"
    assert "warm" in session["instructions"]
    assert "gender" not in json.dumps(ws.sent) and "speed" not in json.dumps(ws.sent)
    assert type(ws.sent[-1]["response"]["max_output_tokens"]) is int


def test_truncated_audio_is_not_saved_or_delivered(tmp_path):
    ws = Socket([{"type": "session.updated"},
                 {"type": "response.output_audio.delta", "delta": "AAAA"},
                 {"type": "response.done", "response": {"status": "incomplete"}}])
    audio = RouterAudio(config(), Mock())
    with patch.object(audio, "connect", return_value=nullcontext(ws)), pytest.raises(RouterServiceError, match="incomplete"):
        audio.synthesize("Ciao.", str(tmp_path / "partial.wav"))
    assert not (tmp_path / "partial.wav").exists()


def test_no_consent_means_no_session_and_no_direct_fallback():
    cfg = config()
    cfg["audio"]["recording_consent"] = False
    client = Mock()
    with pytest.raises(RouterServiceError, match="consent"):
        RouterAudio(cfg, client)
    client.request.assert_not_called()


def test_gateway_local_recovery_cannot_bypass_router_only_selection():
    from tools.transcription_tools import transcribe_audio_local_fallback
    with patch("tools.transcription_tools._load_stt_config", return_value={"provider": "marcel"}), patch("tools.transcription_tools._transcribe_local") as local:
        result = transcribe_audio_local_fallback("unused-fixture.wav")
    assert not result["success"]
    assert "Router-only" in result["error"]
    local.assert_not_called()


def test_realtime_session_creation_uses_actual_transport_contract(tmp_path):
    from agent.router_services import RouterServices
    cfg = config()
    cfg["marcel"] = {"router": {"mode": "marcel_router", "base_url": "https://router.example/api/v1"}}
    client = RouterServices(cfg, key_getter=lambda name: None if name.endswith("_ORIGIN") else "fixture-key")
    response = Mock(status_code=201, headers={"x-marcel-request-id": "fixture-id"})
    response.json.return_value = {"token": "ephemeral-fixture-token"}
    ws = Socket([{"type": "session.updated"},
                 {"type": "response.output_audio.delta", "delta": base64.b64encode(b"\0" * 4800).decode()},
                 {"type": "response.done", "response": {"status": "completed"}}])
    with patch("requests.request", return_value=response) as request, patch("websockets.sync.client.connect", return_value=nullcontext(ws)) as connect:
        RouterAudio(cfg, client).synthesize("Ciao.", str(tmp_path / "reply.wav"))
    assert request.call_count == 1
    kw = request.call_args.kwargs
    assert kw["allow_redirects"] is False
    assert kw["json"]["model"] == "openai/gpt-realtime-2.1"
    assert kw["json"]["recording_consent"] is True
    assert kw["headers"]["X-Client-Request-Id"]
    assert connect.call_args.args[0] == "wss://router.example/api/v1/realtime/connect"
    assert connect.call_args.kwargs["subprotocols"] == ["marcel-realtime", "ephemeral-fixture-token"]


def test_normal_plugin_and_tool_dispatch_respect_saved_audio_preferences(tmp_path, monkeypatch):
    import wave
    import yaml
    from pathlib import Path
    from marcel_cli.plugins import _ensure_plugins_discovered
    from tools.transcription_tools import transcribe_audio
    from tools.tts_tool import text_to_speech_tool
    cfg = config()
    cfg["marcel"] = {"router": {"mode": "marcel_router", "base_url": "https://router.example/api/v1"}}
    cfg["stt"]["cloud_trim_silence"] = False
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    monkeypatch.setenv("MARCEL_ROUTER_API_KEY", "fixture-key")
    monkeypatch.setenv("MARCEL_ROUTER_API_KEY_ORIGIN", "https://router.example")
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    _ensure_plugins_discovered()
    source = tmp_path / "input.wav"
    def write_wav(path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b"\0" * 4800)
    write_wav(source)
    with patch.object(RouterAudio, "transcribe", return_value={"success": True, "transcript": "Ciao."}) as stt:
        result = transcribe_audio(str(source))
    assert result["success"], result
    assert stt.call_args.kwargs["language"] == "it"
    observed = []
    def speech(self, text, output_path, **kwargs):
        observed.append(kwargs)
        assert kwargs.get("voice") in {None, "cedar"}
        assert self.config["tts"]["marcel"]["voice"] == "cedar"
        path = str(Path(output_path).with_suffix(".wav"))
        write_wav(path)
        return path
    with patch.object(RouterAudio, "synthesize", speech):
        result = json.loads(text_to_speech_tool(text="Ciao.", output_path=str(tmp_path / "reply.wav")))
    assert observed
    assert result.get("success") is True or result.get("status") == "success", result
