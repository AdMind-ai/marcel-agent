"""Honest media-service status for the Router-only launch wizard.

A model in /models is not an executable image/video transport. Until a Router
media adapter is qualified, this wizard must not offer its generators or claim
that saving a chat LLM enables media generation.
"""


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
    return result + (
        " — not configured or supported by this Router connection"
        if router_only else " — runtime access not verified"
    )


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
    action = setup.prompt_choice(
        f"Global {kind} generation service",
        ["Keep global service", "Configure global service"],
        0,
    )
    if action == 1:
        setup._info(
            "Only Marcel Router is enabled in this wizard.",
            "No Router image/video generation adapter is integrated. "
            "Catalog entries alone do not prove account access or runtime support.",
            "No direct provider credentials will be requested and no global service was changed.",
            None,
        )
    setup.print_error(
        f"{kind.title()} generation is not configured or supported by this connection. "
        "This worker was not added. A chat model is not a replacement for a media generator."
    )
    return False
