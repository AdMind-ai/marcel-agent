"""Live setup catalog labels; never infer aliases from provider namespaces."""

from contextvars import ContextVar

LIVE_SETUP_CATALOG: ContextVar[list | None] = ContextVar("live_setup_catalog", default=None)


def metadata(entry: dict) -> dict:
    return entry.get("marcel") or entry.get("metadata") or {}


def model_label(entry: dict) -> str:
    meta = metadata(entry)
    model_id = str(entry["id"])
    canonical = entry.get("canonical_id") or meta.get("canonical_id") or entry.get("alias_of") or meta.get("alias_of") or model_id
    provider = entry.get("provider") or meta.get("provider") or entry.get("owned_by") or model_id.split("/")[0]
    name = entry.get("display_name") or meta.get("display_name") or model_id
    available = entry.get("available", meta.get("available", True))
    availability = entry.get("availability", meta.get("availability"))
    status = (
        "requires direct provider connection" if availability == "requires_direct_connection" else
        "unavailable for this account" if available is False or availability == "unavailable" else
        "available via Marcel Router"
    )
    preview = entry.get("preview", meta.get("preview", False)) or "preview" in model_id.lower()
    alias = entry.get("is_alias", meta.get("is_alias", False)) or entry.get("alias_of") or meta.get("alias_of") or canonical != model_id
    capabilities = meta.get("capabilities") or entry.get("capabilities") or {}
    capabilities = ", ".join(key for key, enabled in capabilities.items() if enabled is True) if isinstance(capabilities, dict) else ", ".join(capabilities)
    return (
        f"{name} | canonical: {canonical} | provider: {provider}"
        f" | {status} | capabilities: {capabilities or 'unknown'}"
        f"{' | preview' if preview else ''}"
        f" | {'Marcel alias' if alias else 'native provider ID'}"
        f" [{model_id}]"
    )


def chat_models(catalog: list) -> list[dict]:
    result = []
    for entry in catalog:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        meta = metadata(entry)
        caps = meta.get("capabilities") or entry.get("capabilities") or {}
        from marcel_cli.setup_marcel import _model_capabilities
        capabilities = _model_capabilities({"metadata": {**meta, "capabilities": caps}})
        chat = bool({"chat", "chat_completions", "text", "tool_use", "tools", "supports_tools"} & capabilities)
        tools_denied = isinstance(caps, dict) and caps.get("tools") is False
        if (
            chat and not tools_denied
            and not {"image_generation", "image_editing", "video_generation"} & capabilities
            and entry.get("available", meta.get("available", True)) is not False
            and entry.get("availability", meta.get("availability")) not in {"unavailable", "requires_direct_connection"}
        ):
            result.append(entry)
    return result


def validate_worker_models(workers: list[dict], catalog: list | None) -> None:
    if catalog is None:
        from marcel_cli.setup_marcel import ACTIVITY_MODEL_CHOICES, MODEL_CHOICES
        generators = {model for activity in ("image", "video") for _, model in ACTIVITY_MODEL_CHOICES.get(activity, [])}
        generators -= {model for _, model in MODEL_CHOICES}
        for worker in workers:
            models = [worker.get("model")] + list(worker.get("fallbacks") or worker.get("fallback_models") or [])
            if any(model in generators or str(model or "").startswith("fal-ai/") for model in models):
                raise ValueError("Image/video generation backends cannot be worker chat models")
        return  # Direct/custom endpoints permit operator-provided IDs.
    available = {entry["id"] for entry in chat_models(catalog)}
    for worker in workers:
        models = [worker.get("model")] + list(worker.get("fallbacks") or worker.get("fallback_models") or [])
        if any(model and model not in available for model in models):
            raise ValueError("Worker model/fallback is not an available chat/tool model in this account's catalog")
