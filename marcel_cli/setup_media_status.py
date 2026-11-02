"""Separate Router service configuration from a worker's reasoning LLM."""


def media_kind(activity: str) -> str:
    if activity in ("image", "image_generation"):
        return "image"
    return "video" if activity == "video" else ""


def service_description(config: dict, kind: str, *, router_only: bool) -> str:
    section = config.get(f"{kind}_gen")
    section = section if isinstance(section, dict) else {}
    provider = section.get("provider") or "not configured"
    model = section.get("model") or "not configured"
    result = f"Uses global {kind} service: {provider} / {model}"
    if router_only and (provider != "marcel" or model == "not configured"):
        return result + " — not configured for this Router connection"
    return result + " — account access is verified when the service is called"


def media_worker_ready(setup, activity: str, config: dict, *, router_only: bool) -> bool:
    kind = media_kind(activity)
    if not kind:
        return True
    setup._info(
        f"{kind.title()} generation worker",
        "Reasoning/tool-use model: a chat LLM, separate from the media generator.",
        service_description(config, kind, router_only=router_only),
        "A global service change affects every worker that uses it.",
        None,
    )
    if not router_only:
        return True  # Retained legacy setup owns its separate provider configuration.
    from agent.router_services import RouterServiceError, RouterServices
    try:
        models = RouterServices(config, getattr(setup, "get_env_value", lambda _key: "")).models(kind)
    except (RouterServiceError, OSError):
        setup.print_error(f"Cannot load the Router {kind} catalog. Check the Router connection; no worker was added.")
        return False
    if not models:
        setup.print_error(f"The Router catalog has no available {kind} generation models.")
        return False
    section = config.get(f"{kind}_gen") or {}
    ids = [entry["id"] for entry in models]
    if section.get("provider") == "marcel" and section.get("model") in ids:
        action = setup.prompt_choice(
            f"Global {kind} generation service", ["Keep global service", "Configure global service"], 0,
        )
        if action == 0:
            return True
    selected = setup.prompt_choice(f"Router {kind} generation model", ids + ["Cancel"], (
        ids.index(section["model"]) if section.get("model") in ids else 0
    ))
    if selected not in range(len(ids)):
        return False
    config[f"{kind}_gen"] = {"provider": "marcel", "model": ids[selected]}
    setup._info(f"Global {kind} service: Marcel Router / {ids[selected]}", None)
    return True


def prepare_router_services(values: dict, config: dict) -> None:
    """Make the newly verified connection available before final config serialization."""
    router = config.setdefault("marcel", {}).setdefault("router", {})
    router.update({
        "mode": "marcel_router",
        "base_url": values.get("base_url") or router.get("base_url", ""),
        "key_env": str(values.get("api_key_ref") or router.get("key_env") or "MARCEL_ROUTER_API_KEY")
        .removeprefix("${").removesuffix("}"),
    })


def configure_router_search(setup, config: dict, *, required: bool = False) -> bool:
    from agent.router_services import RouterServiceError, RouterServices
    try:
        sources = RouterServices(config, getattr(setup, "get_env_value", lambda _key: "")).search_providers()
    except (RouterServiceError, OSError):
        setup.print_error("Cannot load Router search services. Check the Router connection.")
        return False
    if not sources:
        setup.print_error("No supported search services are available through this Router.")
        return False
    web = config.get("web") or {}
    current = web.get("search_backend") or web.get("backend")
    ids = [f"marcel-{source}" for source in sources]
    default = ids.index(current) if current in ids else (0 if required else len(ids))
    setup._info(
        "Search service, separate from the research worker's chat LLM.",
        "Uses the Marcel Router key only. A global change affects every worker using web search.",
        None,
    )
    selected = setup.prompt_choice(
        "Router search service",
        [f"{source.title()} — through Marcel Router" for source in sources] + ["Cancel / keep current"],
        default,
    )
    if selected == len(ids):
        return current in ids
    config.setdefault("web", {}).update({"backend": ids[selected], "search_backend": ids[selected]})
    return True
