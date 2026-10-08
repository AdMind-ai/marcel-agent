"""Read disposable runtime records; return allowlisted qualification metadata."""

from __future__ import annotations

import json
import re
import sqlite3


MARKER = "WORKER_ROUTER_PILOT_OK"
SIGNALS = {
    "credentials": r"api.?key|credential|unauthorized|authentication",
    "provider": r"provider|base.?url",
    "budget": r"budget|request.?limit|time.?limit",
    "timeout": r"timeout|timed out",
    "approval": r"approval|permission|denied",
    "model": r"model|not.?found",
    "worker": r"worker",
}


def canonical_call_id(value: str | None) -> str:
    """Match the runtime's composite bridge-ID normalization."""
    return (value or "").split("|", 1)[0].strip()


def decode_payload(content):
    """Decode the runtime's SQLite multimodal sentinel and text blocks."""
    if isinstance(content, str):
        if content.startswith("\x00json:"):
            content = content[len("\x00json:"):]
        try:
            content = json.loads(content)
        except (ValueError, TypeError):
            return None
    if isinstance(content, list):
        parts = [
            item["text"] for item in content
            if isinstance(item, dict) and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        try:
            content = json.loads("\n".join(parts))
        except (ValueError, TypeError):
            return None
    return content if isinstance(content, dict) else None


def successful_worker_result(payload, primary: str) -> bool:
    """Require actual completed model consumption, never an echoed marker."""
    if not isinstance(payload, dict) or payload.get("error"):
        return False
    items = payload.get("results")
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("status") in {"completed", "success"}
        and not item.get("error")
        and isinstance(item.get("api_calls"), int)
        and not isinstance(item.get("api_calls"), bool)
        and item["api_calls"] > 0
        and item.get("model") == primary
        and MARKER in str(item.get("summary", ""))
        for item in items
    )


def collect_delegation_evidence(db: sqlite3.Connection, primary: str) -> dict:
    rows = db.execute(
        "SELECT session_id, role, content, tool_calls, tool_call_id FROM messages ORDER BY rowid"
    ).fetchall()
    registered: set[tuple[str, str]] = set()
    calls = nested_only = 0
    for session_id, role, _, raw_calls, _ in rows:
        if role != "assistant":
            continue
        for call in json.loads(raw_calls or "[]"):
            function = call.get("function", {})
            if function.get("name") != "delegate_task":
                continue
            calls += 1
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if arguments.get("worker") == "imagepilot":
                registered.add((session_id, canonical_call_id(call.get("id"))))
            elif any(
                isinstance(task, dict) and task.get("worker") == "imagepilot"
                for task in arguments.get("tasks", [])
            ):
                # The product accepts worker at the TOP LEVEL only. A nested
                # worker field is stripped and cannot prove named delegation.
                nested_only += 1
    diagnostics = {
        "registered_worker_requested": bool(registered),
        "successful_worker_result": False,
        "delegate_call_count": calls,
        "nested_worker_only_count": nested_only,
        "tool_result_count": 0,
        "matched_tool_result_count": 0,
        "unparsed_tool_result_count": 0,
        "result_error_count": 0,
        "async_dispatch_count": 0,
        "async_completed_count": 0,
        "completed_result_count": 0,
        "model_consumption_result_count": 0,
        "expected_model_result_count": 0,
        "failure_signals": [],
        "message_count": len(rows),
    }
    signals: set[str] = set()
    dispatched: dict[str, str] = {}

    def consume(payload):
        items = payload.get("results", [])
        items = items if isinstance(items, list) else []
        for item in [payload, *items]:
            if not isinstance(item, dict):
                continue
            if item.get("error"):
                diagnostics["result_error_count"] += 1
                for name, pattern in SIGNALS.items():
                    if re.search(pattern, str(item["error"]), re.I):
                        signals.add(name)
        for item in items:
            if not isinstance(item, dict):
                continue
            diagnostics["completed_result_count"] += item.get("status") in {"completed", "success"}
            usage = item.get("api_calls")
            diagnostics["model_consumption_result_count"] += isinstance(usage, int) and usage > 0
            diagnostics["expected_model_result_count"] += item.get("model") == primary
        diagnostics["successful_worker_result"] |= successful_worker_result(payload, primary)

    for session_id, role, content, _, call_id in rows:
        if role != "tool":
            continue
        diagnostics["tool_result_count"] += 1
        payload = decode_payload(content)
        if payload is None:
            diagnostics["unparsed_tool_result_count"] += 1
            continue
        if (session_id, canonical_call_id(call_id)) not in registered:
            continue
        diagnostics["matched_tool_result_count"] += 1
        consume(payload)
        if payload.get("status") == "dispatched" and isinstance(payload.get("delegation_id"), str):
            dispatched[payload["delegation_id"]] = session_id
    diagnostics["async_dispatch_count"] = len(dispatched)
    for delegation_id, parent_session in dispatched.items():
        row = db.execute(
            "SELECT state, parent_session_id, result_json FROM async_delegations WHERE delegation_id = ?",
            (delegation_id,),
        ).fetchone()
        if row and row[0] == "completed" and row[1] == parent_session:
            diagnostics["async_completed_count"] += 1
            payload = decode_payload(row[2])
            if payload is not None:
                consume(payload)
    diagnostics["failure_signals"] = sorted(signals)
    return diagnostics
