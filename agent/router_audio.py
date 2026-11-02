"""File-audio bridge to the Router's documented native OpenAI realtime transport.

No direct-provider credentials, automatic paid retries, partial transcript publication
or partial audio delivery. WebSocket headers and native event bodies are never logged.
"""
from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
import time
import uuid
import wave
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agent.router_services import RouterServiceError, RouterServices

RATE = 24000
VOICES = ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
STYLES = ("natural", "warm", "professional", "energetic")
log = logging.getLogger(__name__)
_socket_log = logging.getLogger(__name__ + ".private_transport")
_socket_log.addHandler(logging.NullHandler())
_socket_log.propagate = False
_socket_log.setLevel(logging.CRITICAL + 1)


class RouterAudio:
    def __init__(self, config=None, client=None):
        if config is None:
            from marcel_cli.config import load_config
            config = load_config()
        self.config = config
        self.client = client or RouterServices(config)
        self.settings = config.get("audio") or {}
        if self.settings.get("recording_consent") is not True or self.settings.get("audio_processing_consent") is not True:
            raise RouterServiceError("Router audio is disabled. Run marcel setup and review the audio consent.", "audio_consent_required")

    @contextmanager
    def connect(self, model, *, task, language=None, transcription_model=None):
        if not isinstance(model, str) or not model.startswith("openai/") or "realtime" not in model:
            raise RouterServiceError("Choose a supported OpenAI realtime model from the Router audio catalog.", "unsupported_model")
        operation = uuid.uuid4().hex
        trace = {"client_request_id": operation, "model": model, "provider": "marcel_router",
                 "task": task, "language_hint": language or "auto", "transcription_model": transcription_model,
                 "timezone": "UTC"}
        log.info("Router audio %s", json.dumps({
            **trace, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "state": "session_requested",
        }))
        try:
            response = self.client.request("POST", "/realtime/sessions", payload={
                "model": model, "recording_consent": True, "audio_processing_consent": True,
            }, client_request_id=operation)
        except RouterServiceError as exc:
            log.info("Router audio %s", json.dumps({
                **trace, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "state": "session_failed",
                "http_status": exc.http_status, "router_request_id": exc.request_id, "error_type": exc.error_type,
            }))
            raise
        try:
            token = response.json()["token"]
            if not isinstance(token, str) or not token or len(token) > 8192:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise RouterServiceError("Router returned an invalid realtime session.", "invalid_response") from None
        parsed = urlsplit(self.client.base)
        url = urlunsplit(("wss" if parsed.scheme == "https" else "ws", parsed.netloc,
                          parsed.path.rstrip("/") + "/realtime/connect", "", ""))
        from websockets.sync.client import connect
        from agent.payload_diagnostics import safe_request_id
        log.info("Router audio %s", json.dumps({
            "client_request_id": operation, "router_request_id": safe_request_id(response.headers.get("x-marcel-request-id")),
            "http_status": response.status_code, "model": model,
            "task": task, "language_hint": language or "auto", "transcription_model": transcription_model,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(), "timezone": "UTC", "state": "session_created",
        }))
        try:
            # The synchronous client does a single handshake; no cross-origin redirects/reconnects.
            with connect(url, subprotocols=["marcel-realtime", token], open_timeout=20,
                         close_timeout=5, max_size=8 * 1024 * 1024, logger=_socket_log) as ws:
                yield ws
        except RouterServiceError:
            raise
        except Exception:
            raise RouterServiceError("Router realtime audio failed. No direct-provider fallback was used.", "realtime_error") from None

    @staticmethod
    def send(ws, event):
        ws.send(json.dumps(event))

    @staticmethod
    def events(ws, deadline):
        while time.monotonic() < deadline:
            try:
                raw = ws.recv(timeout=min(10, max(0.1, deadline - time.monotonic())))
            except TimeoutError:
                continue
            try:
                event = json.loads(raw)
            except (ValueError, TypeError):
                raise RouterServiceError("Invalid Router audio event.", "invalid_response") from None
            if not isinstance(event, dict):
                raise RouterServiceError("Invalid Router audio event.", "invalid_response")
            if event.get("type") in {"error", "conversation.item.input_audio_transcription.failed"}:
                error = event.get("error") or {}
                code = error.get("code")
                allowed_codes = {"invalid_value", "unknown_parameter", "unsupported_parameter",
                                 "invalid_request_error", "model_not_found", "insufficient_quota",
                                 "rate_limit_exceeded", "server_error"}
                known_params = {"session", "session.type", "session.audio", "session.audio.input",
                                "session.audio.input.transcription", "session.audio.input.transcription.model",
                                "session.audio.output", "session.audio.output.voice", "response",
                                "response.max_output_tokens", "response.output_modalities", "model"}
                param = error.get("param")
                log.info("Router audio rejected: code=%s parameter=%s",
                         code if code in allowed_codes else "realtime_rejected",
                         param if param in known_params else "unknown")
                raise RouterServiceError("Router rejected the realtime audio request. Check Router diagnostics.", "realtime_rejected")
            yield event
        raise RouterServiceError("Router audio timed out; no automatic paid retry was made.", "audio_timeout")

    def update(self, ws, session, deadline):
        self.send(ws, {"type": "session.update", "session": session})
        for event in self.events(ws, deadline):
            if event.get("type") == "session.updated":
                return

    def transcribe(self, file_path, *, model=None, language=None, **_extra):
        settings = (self.config.get("stt") or {}).get("marcel") or {}
        model = model or settings.get("model")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RouterServiceError("Router voice input requires ffmpeg.", "dependency_missing")
        try:
            converted = subprocess.run(
                [ffmpeg, "-v", "error", "-nostdin", "-i", str(file_path), "-t", "61",
                 "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
                capture_output=True, timeout=45, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RouterServiceError("Could not decode the audio locally.", "invalid_audio") from None
        pcm = converted.stdout
        if converted.returncode or len(pcm) < RATE // 5 or len(pcm) > RATE * 2 * 60:
            raise RouterServiceError("Send a valid voice clip between 0.1 and 60 seconds.", "invalid_audio")
        transcription = {"model": settings.get("transcription_model") or "gpt-live-transcribe"}
        if language and language not in {"auto", "automatic"}:
            transcription["language"] = language
        deadline = time.monotonic() + 120
        with self.connect(model, task="transcription", language=language, transcription_model=transcription["model"]) as ws:
            self.update(ws, {"type": "realtime", "output_modalities": ["text"], "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": RATE},
                          "transcription": transcription, "turn_detection": None},
            }}, deadline)
            for offset in range(0, len(pcm), 48000):
                self.send(ws, {"type": "input_audio_buffer.append",
                               "audio": base64.b64encode(pcm[offset:offset + 48000]).decode()})
            self.send(ws, {"type": "input_audio_buffer.commit"})
            # Never response.create: ask only for transcription, not an unsolicited spoken answer.
            for event in self.events(ws, deadline):
                if event.get("type") == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript")
                    if not isinstance(text, str) or not text.strip():
                        raise RouterServiceError("Router returned an empty transcript.", "empty_transcript")
                    return {"success": True, "transcript": text.strip(), "provider": "marcel",
                            "model": model, "language": language or "auto"}

    def synthesize(self, text, output_path, *, voice=None, model=None, format="wav", **_extra):
        if self.settings.get("response_mode") == "text_only":
            raise RouterServiceError("Audio replies are disabled by the selected response mode.", "audio_disabled")
        settings = (self.config.get("tts") or {}).get("marcel") or {}
        model = model or settings.get("model")
        voice = voice or settings.get("voice") or "marin"
        style = settings.get("style", "natural")
        if voice not in VOICES or style not in STYLES:
            raise RouterServiceError("Choose a supported Router audio voice and style.", "invalid_audio_settings")
        if not isinstance(text, str) or not text.strip() or len(text) > 3000:
            raise RouterServiceError("Router speech accepts 1–3000 characters per request.", "invalid_text")
        deadline = time.monotonic() + 120
        chunks = []
        with self.connect(model, task="speech") as ws:
            self.update(ws, {"type": "realtime", "output_modalities": ["audio"],
                            "audio": {"output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": voice}},
                            "instructions": f"Read the user's text verbatim in its original language. "
                                            f"Use a {style} speaking style. Do not answer or add commentary."}, deadline)
            self.send(ws, {"type": "conversation.item.create", "item": {"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": text}]}})
            self.send(ws, {"type": "response.create", "response": {"output_modalities": ["audio"], "max_output_tokens": 4096}})
            for event in self.events(ws, deadline):
                if event.get("type") in {"response.output_audio.delta", "response.audio.delta"}:
                    try:
                        chunks.append(base64.b64decode(event["delta"], validate=True))
                    except (KeyError, ValueError, TypeError):
                        raise RouterServiceError("Invalid Router audio data.", "invalid_response") from None
                    if sum(map(len, chunks)) > RATE * 2 * 180:
                        raise RouterServiceError("Router audio exceeded the local duration limit.", "audio_too_large")
                if event.get("type") == "response.done":
                    if (event.get("response") or {}).get("status") != "completed" or not any(chunks):
                        raise RouterServiceError("Router audio was incomplete; no partial voice message was saved.", "incomplete_audio")
                    break
        path = Path(output_path).with_suffix(".wav")
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(RATE)
            stream.writeframes(b"".join(chunks))
        if format in {"ogg", "opus", "mp3"}:
            target = path.with_suffix(".ogg" if format in {"ogg", "opus"} else ".mp3")
            codec = "libopus" if format in {"ogg", "opus"} else "libmp3lame"
            try:
                subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(path),
                                "-c:a", codec, str(target)], capture_output=True, check=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                raise RouterServiceError("Could not encode the Router voice reply.", "audio_encoding_failed") from None
            path.unlink()
            return str(target)
        return str(path)
