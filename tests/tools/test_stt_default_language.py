"""Multilingual installs must not silently force English transcription."""

from marcel_cli.config import DEFAULT_CONFIG
from tools.transcription_tools import _resolve_stt_language


class TestDefaultSttLanguage:
    def test_default_config_detects_language(self):
        assert DEFAULT_CONFIG["stt"]["language"] == "auto"
        assert _resolve_stt_language("openai", DEFAULT_CONFIG["stt"]) is None


    def test_per_provider_still_wins_over_default(self, monkeypatch):
        monkeypatch.delenv("MARCEL_LOCAL_STT_LANGUAGE", raising=False)
        stt = dict(DEFAULT_CONFIG["stt"])
        stt["groq"] = {"language": "he"}
        assert _resolve_stt_language("groq", stt) == "he"
