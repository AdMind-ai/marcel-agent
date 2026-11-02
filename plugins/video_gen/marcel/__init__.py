"""Submit, poll and download Router videos without sending keys to storage hosts."""
from __future__ import annotations

import re
import time
from uuid import uuid4

from agent.router_services import RouterServiceError, RouterServices, configured_service_model, router_available
from agent.video_gen_provider import VideoGenProvider, error_response, save_bytes_video, success_response


class MarcelVideoProvider(VideoGenProvider):
    name = "marcel"
    display_name = "Marcel Router"

    def is_available(self):
        return router_available()

    def list_models(self):
        try:
            return RouterServices().models("video")
        except RouterServiceError:
            return []

    def default_model(self):
        return configured_service_model("video")

    def capabilities(self):
        return {"modalities": ["text"], "max_reference_images": 0}

    def generate(self, prompt, *, model=None, image_url=None, aspect_ratio="16:9",
                 duration=None, resolution=None, **kwargs):
        job_id = kwargs.get("job_id")
        try:
            if image_url or kwargs.get("reference_image_urls"):
                raise RouterServiceError("Router video generation currently supports text prompts only.", "unsupported_modality")
            if not isinstance(prompt, str) or not prompt.strip():
                raise RouterServiceError("A video prompt is required.", "invalid_request")
            client = RouterServices()
            model = model or (client.config.get("video_gen") or {}).get("model")
            if not model:
                raise RouterServiceError("Choose a Router video model in `marcel setup`.", "configuration")
            if not job_id:
                entries = client.models("video")
                entry = next((entry for entry in entries if entry["id"] == model), None)
                if entry is None:
                    raise RouterServiceError("This video model is not available in the Router catalog.", "invalid_request")
                meta = entry.get("metadata") or {}
                duration = duration if duration is not None else 8
                resolution = resolution or "720p"
                if type(duration) is not int:
                    raise RouterServiceError("Video duration must be an integer.", "invalid_request")
                for key, value in (("durations", duration), ("resolutions", resolution), ("aspect_ratios", aspect_ratio)):
                    if meta.get(key) and value not in meta[key]:
                        raise RouterServiceError(f"This Router video model does not support the selected {key}.", "invalid_request")
                combinations = meta.get("valid_combinations", [])
                if combinations and not any(
                    combo.get("duration_seconds") == duration and combo.get("resolution") == resolution
                    for combo in combinations
                ):
                    raise RouterServiceError("Unsupported video duration/resolution combination.", "invalid_request")
                job = client.json("POST", "/videos", payload={
                    "model": model, "prompt": prompt, "duration_seconds": duration,
                    "resolution": resolution, "aspect_ratio": aspect_ratio,
                }, idempotency_key=str(uuid4()))
                job_id = job.get("id")
            if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", job_id):
                raise RouterServiceError("Router returned an invalid video job ID.", "invalid_response")
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                job = client.json("GET", f"/videos/{job_id}")
                state = job.get("status")
                if state == "completed":
                    raw = client.request("GET", f"/videos/{job_id}/content").content
                    if len(raw) < 12 or raw[4:8] != b"ftyp":
                        raise RouterServiceError("Router returned an invalid MP4 file.", "invalid_response")
                    path = save_bytes_video(raw, prefix="marcel")
                    return success_response(
                        video=str(path), model=job.get("model") or model, prompt=prompt,
                        aspect_ratio=aspect_ratio, duration=duration or 0, provider=self.name,
                        extra={"job_id": job_id},
                    )
                if state in {"failed", "deleted", "deleting", "cancelled"}:
                    raise RouterServiceError(f"Router video job ended with status {state}.", "generation_failed")
                if state not in {"queued", "submitting", "in_progress"}:
                    raise RouterServiceError("Router returned an unknown video job status.", "invalid_response")
                time.sleep(3)
            result = error_response(
                error="Video is still processing. Resume this job; do not submit another paid generation.",
                error_type="job_pending", provider=self.name, model=model, prompt=prompt,
            )
            result["job_id"] = job_id
            return result
        except RouterServiceError as exc:
            result = error_response(error=str(exc), error_type=exc.error_type, provider=self.name, model=model or "", prompt=prompt)
            if job_id:
                result["job_id"] = job_id
            return result
        except OSError:
            result = error_response(error="Cannot write the Router video to the local cache.",
                                    error_type="storage_error", provider=self.name, model=model or "", prompt=prompt)
            if job_id:
                result["job_id"] = job_id
            return result


def register(ctx):
    ctx.register_video_gen_provider(MarcelVideoProvider())
