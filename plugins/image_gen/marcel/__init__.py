"""Text-to-image generation through Marcel Router, never direct provider keys."""
from __future__ import annotations

import base64
import binascii
from uuid import uuid4

from agent.image_gen_provider import ImageGenProvider, error_response, resolve_aspect_ratio, success_response
from agent.router_services import RouterServiceError, RouterServices, configured_service_model, router_available


class MarcelImageProvider(ImageGenProvider):
    name = "marcel"
    display_name = "Marcel Router"

    def is_available(self):
        return router_available()

    def list_models(self):
        try:
            return RouterServices().models("image")
        except RouterServiceError:
            return []

    def default_model(self):
        return configured_service_model("image")

    def generate(self, prompt, aspect_ratio="landscape", *, image_url=None, reference_image_urls=None, **kwargs):
        aspect = resolve_aspect_ratio(aspect_ratio)
        model = ""
        try:
            if not isinstance(prompt, str) or not prompt.strip():
                raise RouterServiceError("An image prompt is required.", "invalid_request")
            if image_url or reference_image_urls:
                raise RouterServiceError("Marcel Router currently supports text-to-image only, not editing.", "unsupported_modality")
            client = RouterServices()
            model = kwargs.get("model") or (client.config.get("image_gen") or {}).get("model")
            if not model:
                raise RouterServiceError("Choose a Router image model in `marcel setup`.", "configuration")
            sizes = {"landscape": "1536x1024", "portrait": "1024x1536", "square": "1024x1024"}
            if str(model).startswith("xai/") and aspect != "square":
                raise RouterServiceError("Router xAI image models support square images only.", "unsupported_aspect_ratio")
            payload = {
                "model": model, "prompt": prompt.strip(), "n": 1,
                "size": sizes[aspect], "quality": "medium", "response_format": "b64_json",
            }
            response = client.json("POST", "/images/generations", payload=payload, idempotency_key=str(uuid4()))
            rows = response.get("data")
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise RouterServiceError("Router returned no generated image.", "invalid_response")
            encoded = rows[0].get("b64_json")
            if not isinstance(encoded, str) or len(encoded) > 90_000_000:
                raise RouterServiceError("Router returned invalid image data.", "invalid_response")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise RouterServiceError("Router returned invalid image data.", "invalid_response") from None
            if not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff") or raw[:4] == b"RIFF"):
                raise RouterServiceError("Router returned an unsupported image file.", "invalid_response")
            from marcel_constants import get_marcel_home
            directory = get_marcel_home() / "cache" / "images"
            directory.mkdir(parents=True, exist_ok=True)
            extension = "png" if raw.startswith(b"\x89PNG") else "jpg" if raw.startswith(b"\xff\xd8") else "webp"
            path = directory / f"marcel-{uuid4().hex}.{extension}"
            path.write_bytes(raw)
            return success_response(image=str(path), model=model, prompt=prompt, aspect_ratio=aspect, provider=self.name)
        except RouterServiceError as exc:
            return error_response(error=str(exc), error_type=exc.error_type, provider=self.name, model=model, aspect_ratio=aspect)
        except OSError:
            return error_response(error="Cannot write the Router image to the local cache.",
                                  error_type="storage_error", provider=self.name, model=model, aspect_ratio=aspect)


def register(ctx):
    ctx.register_image_gen_provider(MarcelImageProvider())
