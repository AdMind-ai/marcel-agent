from agent.transcription_provider import TranscriptionProvider
from agent.router_audio import RouterAudio
from agent.router_services import RouterServiceError, router_available


class MarcelTranscriptionProvider(TranscriptionProvider):
    name = "marcel"
    display_name = "Marcel Router realtime"

    def is_available(self):
        return router_available()

    def transcribe(self, file_path, **kwargs):
        try:
            return RouterAudio().transcribe(file_path, **kwargs)
        except RouterServiceError as exc:
            return {"success": False, "error": str(exc), "error_type": exc.error_type}
        except Exception:
            return {"success": False, "error": "Router voice transcription failed.", "error_type": "realtime_error"}


def register(ctx):
    ctx.register_transcription_provider(MarcelTranscriptionProvider())
