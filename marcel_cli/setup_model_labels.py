"""Live setup catalog labels; never infer aliases from provider namespaces."""

from contextvars import ContextVar

LIVE_SETUP_CATALOG: ContextVar[list | None] = ContextVar("live_setup_catalog", default=None)


def metadata(entry: dict) -> dict:
    merged = {}
    for key in ("metadata", "marcel"):
        value = entry.get(key)
        if isinstance(value, dict):
            merged.update(value)
    return merged


def capabilities(entry: dict) -> dict[str, bool]:
    """Adapt explicit Router declarations; never infer tool support from text."""
    meta = metadata(entry)
    raw = entry.get("capabilities")
    if raw is None:
        raw = meta.get("capabilities")
    if isinstance(raw, dict):
        result = {key: value is True for key, value in raw.items() if isinstance(key, str)}
    elif isinstance(raw, (list, tuple)) and all(isinstance(item, str) for item in raw):
        result = dict.fromkeys(raw, True)
    else:
        return {}
    layers = [entry, *(entry[key] for key in ("metadata", "marcel")
                      if isinstance(entry.get(key), dict))]
    supports_tools = entry.get("supports_tool_calls", meta.get("supports_tool_calls"))
    if any(layer.get("supports_tool_calls") is False for layer in layers):
        result["tools"] = False
    elif supports_tools is True:
        result.setdefault("tools", True)
        # Native Router catalog: coding/reasoning describe chat models, and
        # supports_tool_calls explicitly advertises the chat-completions tool
        # protocol. Image generators and embeddings do not satisfy this rule.
        if isinstance(raw, (list, tuple)) and {"coding", "reasoning"} & set(raw):
            if not {"image-generation", "image_generation", "embeddings"} & set(raw):
                result.setdefault("chat", True)
    for layer in layers:
        declared = layer.get("capabilities")
        if isinstance(declared, dict):
            for role in ("chat", "tools", "vision", "video_analysis"):
                if declared.get(role) is False:
                    result[role] = False
    for role, flags in (
        ("vision", ("supports_vision", "supports_image_analysis")),
        ("video_analysis", ("supports_video_analysis",)),
    ):
        if any(layer.get(flag) is False for layer in layers for flag in flags):
            result[role] = False
        elif any(layer.get(flag) is True for layer in layers for flag in flags):
            result.setdefault(role, True)
    if result.get("video") is True or result.get("video-analysis") is True:
        result.setdefault("video_analysis", True)
    return result


def availability(entry: dict) -> str:
    meta = metadata(entry)
    layers = [entry, *(
        value for value in (entry.get("metadata"), entry.get("marcel"))
        if isinstance(value, dict)
    )]
    if any(layer.get("available") is False or layer.get("availability") in (
        "unavailable", "requires_direct_connection",
    ) for layer in layers):
        return "unavailable"
    if any(layer.get("available") is True for layer in layers):
        return "available"
    return "undeclared"


def catalog_summary(catalog: list) -> str:
    states = [availability(entry) if isinstance(entry, dict) else "undeclared" for entry in catalog]
    return (
        f"Catalog entries received: {len(catalog)}. "
        f"Declared available: {states.count('available')}; "
        f"unavailable/direct-only: {states.count('unavailable')}; "
        f"availability not declared: {states.count('undeclared')}. "
        f"Eligible orchestrator models: {len(chat_models(catalog))}."
    )


def model_label(entry: dict) -> str:
    meta = metadata(entry)
    availability_state = availability(entry)
    model_id = str(entry["id"])
    canonical = entry.get("canonical_id") or meta.get("canonical_id") or entry.get("alias_of") or meta.get("alias_of") or model_id
    provider = entry.get("provider") or meta.get("provider") or entry.get("owned_by") or model_id.split("/")[0]
    name = entry.get("display_name") or meta.get("display_name") or model_id
    declared_availability = entry.get("availability", meta.get("availability"))
    status = (
        "requires direct provider connection" if declared_availability == "requires_direct_connection" else
        "unavailable for this account" if availability_state == "unavailable" else
        "available via Marcel Router" if availability_state == "available" else
        "availability not declared"
    )
    preview = entry.get("preview", meta.get("preview", False)) or "preview" in model_id.lower()
    alias = entry.get("is_alias", meta.get("is_alias", False)) or entry.get("alias_of") or meta.get("alias_of") or canonical != model_id
    declared_caps = ", ".join(key for key, enabled in capabilities(entry).items() if enabled)
    return (
        f"{name} [{model_id}] | canonical: {canonical} | provider: {provider}"
        f" | {status} | capabilities: {declared_caps or 'unknown'}"
        f"{' | preview' if preview else ''}"
        f" | {'Marcel alias' if alias else 'native provider ID'}"
    )


def chat_models(catalog: list) -> list[dict]:
    result = []
    for entry in catalog:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        caps = capabilities(entry)
        chat_and_tools = caps.get("chat") is True and caps.get("tools") is True
        if (
            chat_and_tools
            and availability(entry) != "unavailable"
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
    from marcel_cli.setup_activity_models import compatible_models
    for worker in workers:
        available = {entry["id"] for entry in compatible_models(catalog, worker.get("activity", ""))}
        models = [worker.get("model")] + list(worker.get("fallbacks") or worker.get("fallback_models") or [])
        if any(model and model not in available for model in models):
            raise ValueError("Worker model/fallback is not an available chat/tool model "
                             "with the required activity capabilities in this account's catalog")
