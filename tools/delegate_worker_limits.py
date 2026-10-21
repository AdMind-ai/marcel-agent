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
        self.failure_message = None
        self._lock = threading.RLock()
        self._local = threading.local()
        self._operations = {}
        self._totals = dict.fromkeys(
            ("max_input_tokens", "max_output_tokens", "max_total_tokens", "max_cost_usd"), 0,
        )
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
        """Record this thread's main response once, even when both loop hooks run."""
        operation = getattr(self._local, "main_operation", None)
        if operation is not None:
            self.complete_operation(operation, usage=usage, provider=provider, api_mode=api_mode)

    def observe_cost(self, cost_result: Any) -> None:
        operation = getattr(self._local, "main_operation", None)
        if operation is not None:
            self.complete_operation(operation, cost_result=cost_result)

    @staticmethod
    def _number(value: Any, *, integer: bool = False) -> bool:
        try:
            return (
                isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0
                and (not integer or value == int(value))
            )
        except (OverflowError, ValueError):
            return False

    @classmethod
    def usage_values(cls, usage, *, provider="", api_mode=""):
        def value(keys):
            for key in keys:
                v = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
                if cls._number(v, integer=True):
                    return int(v)
            return None
        # Auxiliary adapters expose chat-shaped usage even for native transports.
        prompt = value(("prompt_tokens",))
        inp = prompt if prompt is not None else value(("input_tokens",))
        out = value(("completion_tokens", "output_tokens"))
        native_input = usage.get("input_tokens") if isinstance(usage, dict) else getattr(usage, "input_tokens", None)
        if provider == "anthropic" and prompt is None and native_input is not None and inp is not None:
            inp += (value(("cache_read_input_tokens",)) or 0) + (value(("cache_creation_input_tokens",)) or 0)
        return {
            "max_input_tokens": inp, "max_output_tokens": out,
            "max_total_tokens": inp + out if inp is not None and out is not None else None,
        }

    def check(self, *, include_request_limit: bool = True) -> None:
        """Atomic admission check; costs of other agents never enter this ledger."""
        with self._lock:
            if self.started is None:
                self.started = time.monotonic()
            if self.exhausted:
                raise WorkerBudgetExceeded(self.failure_message or f"Worker budget exhausted: {self.exhausted}")
            for op in self._operations.values():
                if not op["completed"]:
                    continue  # Requests admitted concurrently may finish after the threshold.
                if "max_cost_usd" in self.budget and not op["cost_known"]:
                    self._reject("max_cost_usd",
                        f"Worker cost budget cannot be verified: provider cost estimate unavailable ({op['source']})"
                    )
                for field in ("max_input_tokens", "max_output_tokens", "max_total_tokens"):
                    if field in self.budget and op["tokens_required"] and not op["reported"].get(field):
                        self._reject("token_usage",
                            f"Worker token budget cannot be verified: provider usage unavailable ({op['source']})"
                        )
            usage = {
                **self._totals, "max_requests": self.requests,
                "max_duration_seconds": time.monotonic() - self.started,
            }
            for key, limit in self.budget.items():
                if key == "max_requests" and not include_request_limit:
                    continue  # An admitted external turn may finish; only the next dispatch is blocked.
                if key == "max_cost_usd":
                    limit = Decimal(str(limit))
                if usage[key] >= limit:
                    self._reject(key, f"Worker budget exhausted: {key}")

    def _reject(self, reason, message):
        self.exhausted, self.failure_message = reason, message
        raise WorkerBudgetExceeded(message)

    def begin_operation(self, source: str, api_kwargs: dict | None = None, *, tokens_required=True) -> int:
        with self._lock:
            self.check()
            if api_kwargs is not None:
                caps = [
                    max(1, int(self.budget[key] - self._totals[key]))
                    for key in ("max_output_tokens", "max_total_tokens") if key in self.budget
                ]
                if caps:
                    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                        if key in api_kwargs:
                            api_kwargs[key] = min(api_kwargs[key] or min(caps), min(caps))
                            break
            self.requests += 1
            self._operations[self.requests] = {
                "source": source, "completed": False, "tokens_required": tokens_required,
                "reported": {}, "cost_known": False, "values": {}, "cost": 0, "cost_status": "unknown",
            }
            self._local.active_operation = self.requests
            return self.requests

    def complete_operation(
        self, operation: int, *, usage: Any = None, cost_result: Any = None,
        provider: str = "", api_mode: str = "",
    ) -> None:
        """Replace an operation's contribution, never double-charge repeated hooks."""
        with self._lock:
            op = self._operations[operation]
            op["completed"] = True
            if usage is not None or not op["values"]:
                values = self.usage_values(usage, provider=provider, api_mode=api_mode)
                for key, v in values.items():
                    self._totals[key] += (v or 0) - (op["values"].get(key) or 0)
                op["values"], op["reported"] = values, {k: v is not None for k, v in values.items()}
            if cost_result is not None:
                amount = getattr(cost_result, "amount_usd", None)
                valid_amount = self._number(amount)
                known = valid_amount and getattr(cost_result, "status", "unknown") in {"actual", "estimated", "included"}
                if (getattr(cost_result, "status", "") == "estimated" and op["tokens_required"]
                        and not op["reported"].get("max_total_tokens")):
                    known = False
                cost = Decimal(str(amount)) if valid_amount else Decimal(0)
                self._totals["max_cost_usd"] += cost - op["cost"]
                op["cost"], op["cost_known"] = cost, known
                op["cost_status"] = getattr(cost_result, "status", "unknown") if known else "unknown"

    def snapshot(self) -> dict:
        with self._lock:
            unknown = [
                op["source"] for op in self._operations.values()
                if not op["completed"] or not op["cost_known"]
            ]
            statuses = {op["cost_status"] for op in self._operations.values()}
            status = "unknown" if unknown else (
                "estimated" if "estimated" in statuses else
                "actual" if "actual" in statuses else "included" if statuses else "unknown"
            )
            return {
                "requests": self.requests,
                "input_tokens": self._totals["max_input_tokens"],
                "output_tokens": self._totals["max_output_tokens"],
                "total_tokens": self._totals["max_total_tokens"],
                "cost_usd": float(self._totals["max_cost_usd"]),
                "cost_status": status,
                "unmeasurable_operations": unknown,
                "exhausted": self.exhausted,
            }

    def before_request(self, agent: Any, api_kwargs: dict) -> None:
        previous = getattr(self._local, "main_operation", None)
        with self._lock:
            if previous is not None and not self._operations[previous]["completed"]:
                self.complete_operation(previous)
        self._local.main_operation = self.begin_operation("main_model", api_kwargs)


def constrain_worker_tools(child: Any, config: dict) -> None:
    """Retain an exact execution allowlist as well as narrowing the model schemas."""
    if config.get("permissions") != "selected" and not config.get("tools"):
        return
    allowed = set(child.valid_tool_names)
    if config.get("permissions") == "selected" and config.get("toolsets"):
        from toolsets import resolve_toolset
        selected = {
            tool for toolset in config["toolsets"]
            for tool in resolve_toolset(toolset)
        }
        allowed.intersection_update(selected)
    if config.get("tools"):
        allowed.intersection_update(config["tools"])
    child._worker_allowed_tools = frozenset(allowed)
    child.tools = [tool for tool in child.tools if tool.get("function", {}).get("name") in allowed]
    child.valid_tool_names = allowed
