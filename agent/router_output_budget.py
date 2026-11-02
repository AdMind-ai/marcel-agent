"""Destination-scoped Router output limits and content-free request diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any
from uuid import uuid4
import weakref

logger = logging.getLogger(__name__)

# Router's chat schema, independently of the upstream model's advertised capacity.
# Do not turn a provider default/context window into an upstream output limit.
ROUTER_CHAT_OUTPUT_LIMIT = 32768
TOKEN_FIELDS = ("max_completion_tokens", "max_tokens", "max_output_tokens")
REQUEST_ID_HEADERS = ("x-marcel-request-id", "x-router-request-id", "x-request-id", "request-id")


def _safe_id(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value) else None


def observe_router_client(agent: Any, sdk_client: Any = None) -> None:
    """The SDK only preserves x-request-id; Router emits x-marcel-request-id."""
    import httpx
    if not isinstance(getattr(agent, "_router_client_request_id", None), str):
        return
    client = getattr(sdk_client if sdk_client is not None else getattr(agent, "client", None), "_client", None)
    if not isinstance(client, httpx.Client):
        return
    try:
        owner = weakref.ref(agent)
    except TypeError:
        return
    hooks = client.event_hooks.setdefault("response", [])
    for hook in list(hooks):
        existing = getattr(hook, "_marcel_budget_owner", None)
        if existing is not None and existing() is None:
            hooks.remove(hook)
        elif existing == owner:
            return

    def capture(response):
        current = owner()
        if current is None:
            return
        request_id = response.request.headers.get("x-client-request-id")
        if not request_id or request_id != getattr(current, "_router_client_request_id", None):
            return
        current._router_response_metadata = {
            "client_request_id": request_id, "http_status": response.status_code,
            "router_request_id": next(
                (value for key in REQUEST_ID_HEADERS if (value := _safe_id(response.headers.get(key)))),
                None,
            ),
        }

    capture._marcel_budget_owner = owner
    hooks.append(capture)


def positive_int(value: Any) -> int | None:
    """Accept integers and decimal config strings, never bools/floats/truncation."""
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,12}", value):
            return None
        value = int(value)
    return value if type(value) is int and 0 < value < 10**12 else None


def _same_endpoint(left: Any, right: Any) -> bool:
    from marcel_cli.route_identity import normalize_route_base_url
    return bool(left and right) and normalize_route_base_url(str(left)) == normalize_route_base_url(str(right))


def _router_config(agent: Any) -> dict | None:
    from marcel_cli.config import load_config
    try:
        config = load_config() or {}
    except Exception:
        config = {}
    marcel = config.get("marcel", {})
    marcel = marcel if isinstance(marcel, dict) else {}
    router = marcel.get("router", {})
    router = router if isinstance(router, dict) else {}
    if str(getattr(agent, "provider", "")).lower() == "marcel":
        return marcel
    if router.get("mode") == "marcel_router" and _same_endpoint(
        router.get("base_url"), getattr(agent, "base_url", ""),
    ):
        return marcel
    return None


def _model_limit(config: dict, model: str) -> int | None:
    routing = config.get("routing", {})
    entries = routing.get("model_entries", []) if isinstance(routing, dict) else []
    limits = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("id") != model:
            continue
        meta = entry.get("metadata", {})
        for layer in (entry, meta if isinstance(meta, dict) else {}):
            for key in ("max_output_tokens", "max_completion_tokens", "output_token_limit"):
                value = positive_int(layer.get(key))
                if value is not None:
                    limits.append(value)
    return min(limits) if limits else None


def _event(agent: Any, state: str, **fields: Any) -> None:
    from marcel_time import get_timezone
    now = datetime.now(timezone.utc)
    tz = get_timezone()
    local = now.astimezone(tz)
    record = {
        "client_request_id": getattr(agent, "_router_client_request_id", None),
        "state": state, "model": getattr(agent, "model", None),
        "call_role": "fallback" if type(getattr(agent, "_fallback_index", None)) is int and agent._fallback_index > 0 else "primary",
        "timestamp_utc": now.isoformat(), "timestamp_local": local.isoformat(),
        "timezone": str(tz or local.tzinfo), **fields,
    }
    logger.info("Router request %s", json.dumps(record, sort_keys=True))


def enforce_router_output_budget(agent: Any, kwargs: dict, *, final: bool = False) -> dict:
    """Bound the final wire value without mutating the user's requested budget.

    Re-resolves against the ACTIVE model on every build, including fallback. A
    missing upstream limit stays unknown; it is not equated to the Router cap.
    """
    mode = getattr(agent, "api_mode", "chat_completions")
    if mode not in {"chat_completions", "anthropic_messages", "codex_responses"}:
        agent._router_client_request_id = None
        return kwargs
    config = _router_config(agent)
    if config is None:
        agent._router_client_request_id = None
        return kwargs
    model = str(getattr(agent, "model", ""))
    upstream_limit = _model_limit(config, model)
    limit = min(ROUTER_CHAT_OUTPUT_LIMIT, upstream_limit or ROUTER_CHAT_OUTPUT_LIMIT)
    extra = kwargs.get("extra_body")
    containers = [kwargs, extra] if isinstance(extra, dict) else [kwargs]
    candidates = [container[key] for container in containers for key in TOKEN_FIELDS if key in container]
    valid = [value for candidate in candidates if (value := positive_int(candidate)) is not None]
    invalid_types = sorted({type(value).__name__ for value in candidates if positive_int(value) is None})
    budget = min([limit, *valid])
    if mode == "codex_responses":
        field = "max_output_tokens"
    elif mode == "anthropic_messages":
        field = "max_tokens"
    else:
        field = next(iter(agent._max_tokens_param(budget)))
        if field not in TOKEN_FIELDS:
            raise ValueError("Unsupported Router output token parameter")
    for container in containers:
        for key in TOKEN_FIELDS:
            container.pop(key, None)
    kwargs[field] = int(budget)
    if not final:
        agent._router_client_request_id = None
        agent._router_response_metadata = None
        source = "router_default"
        if candidates:
            source = "serialized_request"
            if getattr(agent, "max_tokens", None) is not None:
                source = "configured_runtime"
            else:
                from providers import get_provider_profile
                profile = get_provider_profile(getattr(agent, "provider", ""))
                source = "provider_profile_default" if profile and profile.default_max_tokens is not None else "model_family_or_request_override"
        agent._router_budget_selection = {
            "model": model, "candidate_source": source,
            "candidate_tokens": min(valid) if valid else None,
            "invalid_candidate_types": invalid_types,
            "router_output_limit": ROUTER_CHAT_OUTPUT_LIMIT, "model_output_limit": upstream_limit,
            "model_limit_source": "saved_router_catalog" if upstream_limit is not None else None,
        }
    else:
        agent._router_client_request_id = str(uuid4())
        agent._router_response_metadata = None
        observe_router_client(agent)
        headers = dict(kwargs.get("extra_headers") or {})
        # Always use our own random, content-free ID, never a session/chat identifier.
        for key in list(headers):
            if key.lower() == "x-client-request-id":
                del headers[key]
        headers["X-Client-Request-Id"] = agent._router_client_request_id
        kwargs["extra_headers"] = headers
        selection = getattr(agent, "_router_budget_selection", {})
        selection = selection if isinstance(selection, dict) and selection.get("model") == model else {}
        _event(
            agent, "prepared", **{k: v for k, v in selection.items() if k != "model"},
            parameter=field, serialized_value=budget, serialized_type="int",
            final_invalid_candidate_types=invalid_types,
        )
    return kwargs


def record_router_result(agent: Any, *, response: Any = None, error: Any = None) -> None:
    """Record only allowlisted IDs/status, never errors, headers, prompts or keys."""
    if not isinstance(getattr(agent, "_router_client_request_id", None), str):
        return
    value = error if error is not None else response
    request_id = _safe_id(getattr(value, "request_id", None)) or _safe_id(getattr(value, "_request_id", None))
    http_response = getattr(value, "response", None)
    if request_id is None and http_response is not None:
        headers = getattr(http_response, "headers", {})
        request_id = next((header_id for key in REQUEST_ID_HEADERS if (header_id := _safe_id(headers.get(key)))), None)
    observed = getattr(agent, "_router_response_metadata", None)
    observed = observed if isinstance(observed, dict) and observed.get("client_request_id") == agent._router_client_request_id else {}
    request_id = request_id or observed.get("router_request_id")
    status = getattr(value, "status_code", None)
    _event(agent, "failed" if error is not None else "response_received",
           router_request_id=request_id,
           exception_type=type(error).__name__ if error is not None else None,
           http_status=status if type(status) is int else observed.get("http_status", 200 if error is None else None))
