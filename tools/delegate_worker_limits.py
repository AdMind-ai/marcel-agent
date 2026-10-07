"""Per-run worker resource limits, shared admission, and tool allowlists."""

from __future__ import annotations

import threading
import time
import math
from decimal import Decimal
from typing import Any

from tools.delegate_worker_registry import _BUDGET_FIELDS

_ADMISSION_LOCK = threading.Lock()


class WorkerBudgetExceeded(RuntimeError):
    pass


class WorkerLimits:
    def __init__(self, config: dict, parent: Any):
        self.budget = {key: config[key] for key in _BUDGET_FIELDS if key in config}
        self.budget.update(config.get("budget") or {})
        self.started = None
        self.requests = 0
        self.exhausted = None
        self._token_reporting = {}
        self._cost_reporting = False
        self.timeout = config.get("timeout_seconds")
        self.permissions = config.get("permissions", "inherit")
        self.tools = config.get("tools")
        self.worker_id = config["id"]
        with _ADMISSION_LOCK:
            if not isinstance(getattr(parent, "_worker_admission", None), dict):
                parent._worker_admission = {}
            cap = config.get("max_concurrency", 10)
            self.admission = parent._worker_admission.setdefault(
                self.worker_id, threading.BoundedSemaphore(cap),
            )

    def deadline(self, global_timeout: float | None) -> float | None:
        limits = [v for v in (
            global_timeout,
            self.timeout,
            self.budget.get("max_duration_seconds"),
        ) if v and v > 0]
        return min(limits) if limits else None

    def observe_completed_attempt(self, usage: Any, *, provider: str = "", api_mode: str = "") -> None:
        """Replace reporting state for this attempt; session totals may be stale."""
        def reported(keys):
            for key in keys:
                value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
                if (isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) and value >= 0 and value == int(value)):
                    return True
            return False

        native = provider == "anthropic" or api_mode in {"anthropic_messages", "codex_responses"}
        input_reported = reported(("input_tokens",) if native else ("prompt_tokens", "input_tokens"))
        output_reported = reported(("output_tokens",) if native else ("completion_tokens", "output_tokens"))
        self._token_reporting = {
            "max_input_tokens": input_reported,
            "max_output_tokens": output_reported,
            "max_total_tokens": input_reported and output_reported,
        }
        # Set only by the current attempt's pricing result, never by the session's last status.
        self._cost_reporting = False

    def observe_cost(self, cost_result: Any) -> None:
        amount = getattr(cost_result, "amount_usd", None)
        self._cost_reporting = (
            self._token_reporting.get("max_total_tokens", False)
            and getattr(cost_result, "status", "unknown") != "unknown"
            and isinstance(amount, (int, float, Decimal)) and not isinstance(amount, bool)
            and math.isfinite(amount) and amount >= 0
        )

    def before_request(self, agent: Any, api_kwargs: dict) -> None:
        """Every main-model attempt, including retries and schema repair, counts."""
        if self.started is None:
            self.started = time.monotonic()
        usage = {
            "max_requests": self.requests,
            "max_input_tokens": getattr(agent, "session_input_tokens", 0),
            "max_output_tokens": getattr(agent, "session_output_tokens", 0),
            "max_total_tokens": getattr(agent, "session_total_tokens", 0),
            "max_cost_usd": getattr(agent, "session_estimated_cost_usd", 0) or 0,
            "max_duration_seconds": time.monotonic() - self.started,
        }
        if self.requests:
            if "max_cost_usd" in self.budget and not self._cost_reporting:
                self.exhausted = "max_cost_usd"
                raise WorkerBudgetExceeded("Worker cost budget cannot be verified: provider cost estimate unavailable")
            token_fields = {"max_input_tokens", "max_output_tokens", "max_total_tokens"} & self.budget.keys()
            if any(not self._token_reporting.get(field, False) for field in token_fields):
                self.exhausted = "token_usage"
                raise WorkerBudgetExceeded("Worker token budget cannot be verified: provider usage unavailable")
        for key, limit in self.budget.items():
            if usage[key] >= limit:
                self.exhausted = key
                raise WorkerBudgetExceeded(f"Worker budget exhausted: {key}")
        # Token/cost counters are provider usage, not an exact prepaid billing cap.
        # Once a response crosses a threshold no further request may be sent.
        caps = []
        for key in ("max_output_tokens", "max_total_tokens"):
            if key in self.budget:
                caps.append(max(1, int(self.budget[key] - usage[key])))
        if caps:
            cap = min(caps)
            for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                if key in api_kwargs:
                    api_kwargs[key] = min(api_kwargs[key], cap) if api_kwargs[key] else cap
                    break
        self.requests += 1
        # Fail closed if this dispatch returns without completing the reporting hooks.
        self._token_reporting = {}
        self._cost_reporting = False


def constrain_worker_tools(child: Any, config: dict) -> None:
    """Retain an exact execution allowlist as well as narrowing the model schemas."""
    if config.get("permissions") != "selected" and not config.get("tools"):
        return
    allowed = set(child.valid_tool_names)
    if config.get("permissions") == "selected" and config.get("toolsets"):
        from toolsets import resolve_multiple_toolsets
        allowed.intersection_update(resolve_multiple_toolsets(config["toolsets"]))
    if config.get("tools"):
        allowed.intersection_update(config["tools"])
    child._worker_allowed_tools = frozenset(allowed)
    child.tools = [tool for tool in child.tools if tool.get("function", {}).get("name") in allowed]
    child.valid_tool_names = allowed
