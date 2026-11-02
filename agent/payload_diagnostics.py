"""Content-free request measurements: bytes are not context/output tokens."""
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from uuid import uuid4

logger = logging.getLogger(__name__)


def compact_utf8_input(text, limit):
    """Evenly sample a bounded retry input; archived originals remain authoritative."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    marker = "\n[... archived content omitted; recover using session_search ...]\n"
    width = max(1, (limit - 7 * len(marker.encode())) // 8)
    return marker.join(
        raw[int(i * (len(raw) - width) / 7):int(i * (len(raw) - width) / 7) + width].decode("utf-8", errors="ignore")
        for i in range(8)
    )


def serialized_bytes(value):
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return None


def payload_metrics(messages, tools=None):
    rows = messages if isinstance(messages, list) else []
    definitions = tools if isinstance(tools, list) else []
    inline_bytes = 0
    fingerprints = []

    def visit(value):
        nonlocal inline_bytes
        if isinstance(value, str) and value.startswith("data:") and ";base64," in value[:160]:
            inline_bytes += len(value.encode("utf-8"))
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for row in rows:
        visit(row)
        if isinstance(row, dict):
            fingerprints.append(hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).digest())
    from agent.model_metadata import estimate_request_tokens_rough
    return {
        "message_count": len(rows), "messages_bytes": serialized_bytes(rows),
        "tools_count": len(definitions), "tools_bytes": serialized_bytes(definitions),
        "tool_results_bytes": serialized_bytes([m for m in rows if isinstance(m, dict) and m.get("role") == "tool"]),
        "system_bytes": serialized_bytes([m for m in rows if isinstance(m, dict) and m.get("role") in {"system", "developer"}]),
        "inline_media_bytes": inline_bytes, "duplicate_message_count": len(fingerprints) - len(set(fingerprints)),
        "estimated_request_tokens": estimate_request_tokens_rough(rows, tools=definitions or None),
        "token_estimate_source": "rough_messages_and_tools_estimator",
    }


def wire_metrics(kwargs):
    body = {k: v for k, v in kwargs.items() if k not in {"extra_headers", "extra_query", "extra_body", "timeout"}}
    if isinstance(kwargs.get("extra_body"), dict):
        body.update(kwargs["extra_body"])
    return {**payload_metrics(body.get("messages"), body.get("tools")),
            "serialized_body_bytes": serialized_bytes(body)}


def http_status(error):
    status = getattr(error, "status_code", None)
    if type(status) is not int:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return status if type(status) is int else None


def safe_request_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value) else None


def log_summary_request(messages, route, *, response=None, error=None, elapsed_ms=0, client_request_id=None):
    """Never log prompts, error bodies, headers, credentials, or summaries."""
    value = error if error is not None else response
    request_id = safe_request_id(getattr(value, "request_id", None)) or safe_request_id(getattr(value, "_request_id", None))
    raw = getattr(value, "response", None)
    headers = getattr(raw, "headers", {})
    request_id = request_id or next(
        (rid for key in ("x-marcel-request-id", "x-router-request-id", "x-request-id")
         if (rid := safe_request_id(headers.get(key)))), None,
    )
    content = getattr(getattr(raw, "request", None), "content", None)
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    reasoning_tokens = getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None)
    record = {
        "event": "compression_request", "time_utc": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC", "operation_id": str(uuid4()), "request_id": request_id,
        "client_request_id": client_request_id,
        "provider": route.get("provider"), "model": route.get("model"),
        "http_status": http_status(error) if error is not None else 200,
        "failure_class": type(error).__name__ if error is not None else None,
        "serialized_body_bytes": len(content) if isinstance(content, bytes) else None,
        "http_413_origin": "unknown" if error is not None and http_status(error) == 413 else None,
        "output_budget_requested": None, "output_budget_source": "auxiliary_provider_default",
        "prompt_tokens": prompt_tokens if type(prompt_tokens) is int else None,
        "completion_tokens": completion_tokens if type(completion_tokens) is int else None,
        "reasoning_tokens": reasoning_tokens if type(reasoning_tokens) is int else None,
        "elapsed_ms": elapsed_ms, **payload_metrics(messages),
    }
    logger.info("Compression request %s", json.dumps(record, sort_keys=True))
