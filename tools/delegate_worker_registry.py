"""Declarative named workers for :mod:`tools.delegate_tool`.

``delegation.workers`` may be either a mapping keyed by worker id or a list of
objects with an ``id`` field.  Values are deliberately configuration only:
this module neither resolves credentials nor returns credential-like values.

Resolution precedence is **delegation defaults < named worker < call
overrides**.  Only the fields below participate in that merge, which keeps a
worker declaration from accidentally becoming a second credential store.
``delegate_task`` currently consumes provider, model, iterations, and
concurrency.  The next localized integration points for remaining metadata are
``_resolve_child_toolsets`` (tools/toolsets), ``_resolve_child_runtime``
(fallback_models), ``_get_child_timeout`` (timeout_seconds), and child cost
accounting (budget fields).
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, Mapping, Optional


class WorkerConfigError(ValueError):
    """A worker declaration is malformed or names an unknown worker."""


_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_ROLES = frozenset({"leaf", "orchestrator"})
_SECRET_MARKERS = ("api_key", "apikey", "secret", "password", "credential")
_BUDGET_FIELDS = frozenset({
    "max_cost_usd", "max_input_tokens", "max_output_tokens", "max_total_tokens",
    "max_requests", "max_duration_seconds",
})
_FIELDS = frozenset({
    "activity", "role", "provider", "model", "tools", "toolsets",
    "max_concurrency", "max_iterations", "timeout_seconds", "fallback_models",
    "budget", *_BUDGET_FIELDS,
    "permissions", "image_service",
})


def _has_secret_key(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_has_secret_key(item) for item in value)
    if not isinstance(value, Mapping):
        return False
    for key, child in value.items():
        normalized = str(key).strip().lower().replace("-", "_")
        # ``max_total_tokens`` is a budget, not a credential.  Treat token as
        # sensitive only in the singular credential spelling.
        if (any(marker in normalized for marker in _SECRET_MARKERS)
                or normalized == "token" or normalized.endswith("_token")):
            return True
        if _has_secret_key(child):
            return True
    return False


def _positive_int(value: Any, field: str) -> int:
    # bool is an int subclass but never a meaningful resource limit.
    if isinstance(value, bool):
        raise WorkerConfigError(f"{field} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkerConfigError(f"{field} must be a positive integer") from exc
    if parsed <= 0 or str(value).strip() not in {str(parsed), f"+{parsed}"}:
        raise WorkerConfigError(f"{field} must be a positive integer")
    return parsed


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise WorkerConfigError(f"{field} must be a non-empty list of strings")
    return [_string(item, field) for item in value]


def _budget(value: Any, field: str = "budget") -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkerConfigError(f"{field} must be a mapping")
    if _has_secret_key(value):
        raise WorkerConfigError(f"{field} must not contain secrets")
    unknown = set(value) - _BUDGET_FIELDS
    if unknown:
        raise WorkerConfigError(f"{field} has unsupported field(s): {', '.join(sorted(map(str, unknown)))}")
    normalized: Dict[str, Any] = {}
    for key, raw in value.items():
        if key == "max_cost_usd":
            if isinstance(raw, bool):
                raise WorkerConfigError(f"{field}.{key} must be a positive number")
            try:
                parsed = float(raw)
            except (TypeError, ValueError) as exc:
                raise WorkerConfigError(f"{field}.{key} must be a positive number") from exc
            if not math.isfinite(parsed) or parsed <= 0:
                raise WorkerConfigError(f"{field}.{key} must be a positive number")
            normalized[key] = parsed
        else:
            normalized[key] = _positive_int(raw, f"{field}.{key}")
    return normalized


def _validate_values(raw: Mapping[str, Any], *, worker_id: Optional[str] = None) -> Dict[str, Any]:
    if _has_secret_key(raw):
        raise WorkerConfigError("worker declarations must not contain secrets")
    unknown = set(raw) - _FIELDS - {"id"}
    if unknown:
        raise WorkerConfigError(f"worker has unsupported field(s): {', '.join(sorted(map(str, unknown)))}")
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        if key == "id":
            continue
        if key in {"activity", "provider", "model"}:
            result[key] = _string(value, key)
        elif key == "image_service":
            if value != "global":
                raise WorkerConfigError("image_service must be 'global'")
            result[key] = value
        elif key == "role":
            role = _string(value, key).lower()
            if role not in _ROLES:
                raise WorkerConfigError("role must be 'leaf' or 'orchestrator'")
            result[key] = role
        elif key in {"tools", "toolsets", "fallback_models"}:
            result[key] = _string_list(value, key)
        elif key in {"max_concurrency", "max_iterations"}:
            result[key] = _positive_int(value, key)
        elif key == "timeout_seconds":
            # Zero is an intentional "no deadline" setting, matching delegation.child_timeout_seconds.
            if isinstance(value, bool):
                raise WorkerConfigError("timeout_seconds must be a number")
            try:
                timeout = float(value)
            except (TypeError, ValueError) as exc:
                raise WorkerConfigError("timeout_seconds must be a number") from exc
            if not math.isfinite(timeout) or timeout < 0:
                raise WorkerConfigError("timeout_seconds must be zero or a positive number")
            result[key] = timeout
        elif key == "budget":
            result[key] = _budget(value)
        elif key == "permissions":
            if not isinstance(value, str) or value not in {"inherit", "selected"}:
                raise WorkerConfigError("permissions must be 'inherit' or 'selected'")
            result[key] = value
        elif key in _BUDGET_FIELDS:
            result[key] = _budget({key: value}, "budget")[key]
    if worker_id is not None:
        result["id"] = worker_id
    if result.get("permissions") == "selected" and not (
        result.get("tools") or result.get("toolsets")
    ):
        raise WorkerConfigError("selected permissions require tools or toolsets")
    return result


def parse_workers(workers: Any) -> Dict[str, Dict[str, Any]]:
    """Validate and normalize an unbounded mapping/list of worker declarations."""
    if workers is None:
        return {}
    items = []
    if isinstance(workers, Mapping):
        items = list(workers.items())
    elif isinstance(workers, list):
        for entry in workers:
            if not isinstance(entry, Mapping):
                raise WorkerConfigError("delegation.workers list entries must be mappings")
            items.append((entry.get("id"), entry))
    else:
        raise WorkerConfigError("delegation.workers must be a mapping or list")

    parsed: Dict[str, Dict[str, Any]] = {}
    for key, declaration in items:
        worker_id = _string(key, "worker id")
        if not _ID_RE.fullmatch(worker_id):
            raise WorkerConfigError("worker id must start with a letter and contain only letters, digits, '.', '_' or '-'")
        if not isinstance(declaration, Mapping):
            raise WorkerConfigError(f"worker '{worker_id}' must be a mapping")
        embedded_id = declaration.get("id")
        if embedded_id is not None and _string(embedded_id, "worker id") != worker_id:
            raise WorkerConfigError(f"worker key '{worker_id}' does not match id '{embedded_id}'")
        if worker_id in parsed:
            raise WorkerConfigError(f"duplicate worker id '{worker_id}'")
        parsed[worker_id] = _validate_values(declaration, worker_id=worker_id)
    return parsed


def _global_defaults(delegation_config: Mapping[str, Any]) -> Dict[str, Any]:
    """Translate compatible legacy delegation keys into registry field names."""
    source: Dict[str, Any] = {}
    for field in _FIELDS:
        value = delegation_config.get(field)
        # Empty strings are conventional "inherit" sentinels in config.yaml,
        # not malformed global defaults.
        if value is not None and not (field in {"activity", "provider", "model"} and isinstance(value, str) and not value.strip()):
            source[field] = value
    if "max_concurrent_children" in delegation_config and "max_concurrency" not in source:
        source["max_concurrency"] = delegation_config["max_concurrent_children"]
    if "child_timeout_seconds" in delegation_config and "timeout_seconds" not in source:
        source["timeout_seconds"] = delegation_config["child_timeout_seconds"]
    return _validate_values(source)


def resolve_worker(
    worker_id: str, delegation_config: Optional[Mapping[str, Any]], call_overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a safe, normalized effective worker configuration.

    The returned dictionary never contains API keys, tokens, passwords, or
    credential objects.  ``call_overrides`` is intentionally limited to the
    same public worker fields and wins over a configured worker.
    """
    config = delegation_config or {}
    if not isinstance(config, Mapping):
        raise WorkerConfigError("delegation config must be a mapping")
    worker_id = _string(worker_id, "worker id")
    workers = parse_workers(config.get("workers"))
    if worker_id not in workers:
        raise WorkerConfigError(f"unknown delegation worker '{worker_id}'")
    overrides = _validate_values(call_overrides or {})
    result = _global_defaults(config)
    result.update(copy.deepcopy(workers[worker_id]))
    result.update(overrides)
    result["id"] = worker_id
    return result