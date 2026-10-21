"""Consumption/cancellation contract for opaque external agent turns.

Requests mean externally admitted prompts/turns, NOT hidden model/tool calls.
Token thresholds use reported consumption and cannot undo already billed work.
"""

from __future__ import annotations

import threading
import time
import logging

from tools.delegate_worker_limits import WorkerBudgetExceeded


def validate_external_budget(budget, transport):
    """Both supported wires report tokens optionally, but no reliable USD receipt."""
    if "max_cost_usd" in budget:
        raise ValueError(
            f"Worker max_cost_usd is not supported by {transport}: "
            "the external agent does not expose verifiable USD costs. "
            "Use request/duration limits or a provider-side spending cap."
        )


def cancel_external_process(send_cancel, close):
    """A blocked stdin write must not prevent force-stop at the deadline."""
    def notify():
        try:
            send_cancel()
        except Exception:
            pass  # Process closure is authoritative; the protocol interrupt is best effort.

    sender = threading.Thread(target=notify, daemon=True)
    sender.start()
    sender.join(timeout=0.1)
    close()


class ExternalWorkerOperation:
    """Borrow a local/auxiliary reservation, or admit one external turn exactly once.

    The deadline covers handshake and execution. Cancellation must stop the
    process as well as request a protocol interrupt: remote peers can ignore it.
    """

    def __init__(self, limits, transport, cancel):
        self.limits, self.transport, self.cancel = limits, transport, cancel
        self.operation = None
        self.timer = None
        self._done = threading.Event()
        self._cancelled = False
        self._cancel_lock = threading.Lock()
        self._cancel_done = threading.Event()

    def __enter__(self):
        if self.limits is None:
            return self
        validate_external_budget(self.limits.budget, self.transport)
        with self.limits._lock:
            active = getattr(self.limits._local, "active_operation", None)
            if active is not None and not self.limits._operations[active]["completed"]:
                self.operation = active
                self.limits.check(include_request_limit=False)
                self.limits._operations[active]["source"] = f"external:{self.transport}"
            else:
                self.operation = self.limits.begin_operation(f"external:{self.transport}")
        duration = self.limits.budget.get("max_duration_seconds")
        if duration is not None:
            remaining = self.limits.started + duration - time.monotonic()
            self.timer = threading.Timer(max(0, remaining), self._expire)
            self.timer.daemon = True
            self.timer.start()
        return self

    def _stop(self):
        with self._cancel_lock:
            first = not self._cancelled
            self._cancelled = True
        if not first:
            self._cancel_done.wait()
            return
        try:
            self.cancel()
        except Exception:
            logging.getLogger(__name__).exception("External worker cancellation failed")
        finally:
            self._cancel_done.set()

    def _expire(self):
        with self.limits._lock:
            if self._done.is_set():
                return
            if not self.limits.exhausted:
                self.limits.exhausted = "max_duration_seconds"
                self.limits.failure_message = "Worker budget exhausted: max_duration_seconds"
        self._stop()

    def check(self):
        if self.limits is not None:
            try:
                self.limits.check(include_request_limit=False)
            except WorkerBudgetExceeded:
                self._stop()
                raise

    def report(self, usage):
        if self.limits is not None:
            self.limits.complete_operation(self.operation, usage=usage if usage is not None else {})
            self.check()

    def __exit__(self, exc_type, exc, tb):
        if self.limits is not None:
            with self.limits._lock:
                self._done.set()
        else:
            self._done.set()
        if self.timer is not None:
            self.timer.cancel()
        if self.limits is not None:
            # No reported data must remain unknown, never a synthetic zero.
            with self.limits._lock:
                op = self.limits._operations[self.operation]
                if not op["completed"]:
                    self.limits.complete_operation(self.operation)
            self.check()
        return False


def codex_total_usage(raw):
    """Only cumulative thread totals cover ALL internal model calls, unlike `last`."""
    if not isinstance(raw, dict):
        return None
    from tools.delegate_worker_limits import WorkerLimits
    inp, out = raw.get("inputTokens"), raw.get("outputTokens")
    if not all(WorkerLimits._number(v, integer=True) for v in (inp, out)):
        return None
    return {"input_tokens": int(inp), "output_tokens": int(out)}
