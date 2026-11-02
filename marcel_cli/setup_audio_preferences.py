"""Input-language and transcript privacy preferences, without adding credentials."""
import re
import shutil


def prepare_router_audio(config):
    """Do not leave a hidden direct/default audio provider active in Router-only setup."""
    if (config.get("stt") or {}).get("provider") != "marcel":
        config.setdefault("stt", {}).update({"provider": "marcel", "enabled": False})
    if (config.get("tts") or {}).get("provider") != "marcel":
        config.setdefault("tts", {})["provider"] = "marcel"


def configure_router_audio(setup, config):
    from agent.router_audio import STYLES, VOICES
    from agent.router_services import RouterServiceError, RouterServices
    prepare_router_audio(config)
    if not shutil.which("ffmpeg"):
        setup.print_error("Install ffmpeg before enabling Router audio. No external audio provider was enabled.")
        return False
    try:
        models = RouterServices(config, getattr(setup, "get_env_value", lambda _key: "")).models("audio")
    except (RouterServiceError, OSError):
        setup.print_error("Could not load the Router realtime audio catalog. No audio provider was enabled.")
        return False
    if not models:
        setup.print_error("No compatible Router audio model is available. No direct-provider fallback was enabled.")
        return False
    setup._info(
        "Router file-audio adapter: OpenAI realtime. Google realtime is not yet supported by this adapter.",
        "Voice input is transcribed, not translated; clips must be 0.1–60 seconds.",
        "Enabling this service requires consent to audio processing and recording through the Router.",
        None,
    )
    pick = setup.prompt_choice("Router audio provider and model", [row.get("name") or row["id"] for row in models] + ["Cancel"], 0)
    if pick >= len(models):
        return False
    if not setup.prompt_yes_no("Consent to Router audio processing and recording?", default=False):
        config.setdefault("audio", {}).update(recording_consent=False, audio_processing_consent=False)
        config["stt"]["enabled"] = False
        config.setdefault("voice", {})["auto_tts"] = False
        setup._info("Router audio remains disabled; no external provider was enabled.", None)
        return False
    if not configure_audio_preferences(setup, config):
        return False
    asr_models = ("gpt-live-transcribe", "gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1")
    asr_model = asr_models[setup.prompt_choice("Native transcription engine through Router", list(asr_models), 0)]
    voice_pick = setup.prompt_choice("Preferred voice", ["Marin (feminine)", "Cedar (masculine)", "Choose another supported voice"], 0)
    voice = ("marin", "cedar")[voice_pick] if voice_pick < 2 else VOICES[
        setup.prompt_choice("Supported OpenAI realtime voice", list(VOICES), 0)]
    style = STYLES[setup.prompt_choice("Speaking style", list(STYLES), 0)]
    modes = ("text_only", "on_request", "voice_to_voice")
    mode = modes[setup.prompt_choice("Audio response mode", [
        "Text replies only", "Audio when explicitly requested", "Voice replies to voice messages",
    ], 1)]
    model = models[pick]["id"]
    config.setdefault("audio", {}).update(recording_consent=True, audio_processing_consent=True, response_mode=mode)
    config["stt"].update(enabled=True, provider="marcel")
    config["stt"].setdefault("marcel", {}).update(model=model, transcription_model=asr_model)
    config["tts"]["marcel"] = {"model": model, "voice": voice, "style": style}
    config.setdefault("voice", {})["auto_tts"] = mode == "voice_to_voice"
    setup._info(
        f"Router audio: {model}; transcription engine: {asr_model}.",
        f"Voice: {voice}; style: {style}; response mode: {mode}.",
        "Voice character selects an actual voice ID; no unsupported gender/pitch/speed parameter is sent.",
        "Chat-specific /voice settings override the automatic reply default. Text-only mode also disables speech generation.",
        "Restart the gateway after saving these settings. Account access is verified on the first audio request.",
        None,
    )
    return True


def configure_audio_preferences(setup, config):
    stt = config.get("stt") or {}
    current = str(stt.get("language") or "auto").lower()
    options = ["Auto-detect input language", "Prefer Italian (it)", "Another preferred language"]
    default = 0 if current in {"auto", "automatic"} else (1 if current == "it" else 2)
    selected = setup.prompt_choice("Voice input language", options, default)
    language = "auto" if selected == 0 else "it"
    if selected == 2:
        language = setup.prompt("Preferred language code", default=current if default == 2 else "").strip().lower().split("-")[0]
        if not re.fullmatch(r"[a-z]{2}", language):
            setup.print_error("Use a two-letter language code, for example it, en, es or fr.")
            return False
    echo = setup.prompt_yes_no("Publish voice transcripts in chat?", default=False)
    config.setdefault("stt", {}).update({"language": language, "echo_transcripts": echo})
    provider = stt.get("provider")
    if provider and isinstance(config["stt"].get(provider), dict):
        config["stt"][provider]["language"] = language
    # Replace a previously saved gateway override only when one already exists.
    if "stt_echo_transcripts" in config:
        config["stt_echo_transcripts"] = echo
    if isinstance(config.get("gateway"), dict) and "stt_echo_transcripts" in config["gateway"]:
        config["gateway"]["stt_echo_transcripts"] = echo
    setup._info(
        f"STT input language: {language}. Transcripts remain available internally.",
        f"Publish transcripts: {'enabled' if echo else 'disabled'}; independent of tool progress.",
        "These settings do not select or authorize another audio provider.",
        "Restart a running gateway after saving audio preferences.",
        None,
    )
    return True
