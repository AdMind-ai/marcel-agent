from agent.tts_provider import TTSProvider
from agent.router_audio import RouterAudio, VOICES
from agent.router_services import router_available


class MarcelTTSProvider(TTSProvider):
    name = "marcel"
    display_name = "Marcel Router realtime"

    def is_available(self):
        return router_available()

    def list_voices(self):
        return [{"id": voice, "display": voice.title()} for voice in VOICES]

    def synthesize(self, text, output_path, **kwargs):
        return RouterAudio().synthesize(text, output_path, **kwargs)


def register(ctx):
    ctx.register_tts_provider(MarcelTTSProvider())
