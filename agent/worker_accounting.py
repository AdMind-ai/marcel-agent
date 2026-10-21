"""Per-worker ambient accounting, isolated across turns and copied to tool threads."""

from contextvars import ContextVar
from functools import wraps
from types import SimpleNamespace
from decimal import Decimal
import json

from tools.delegate_worker_limits import WorkerBudgetExceeded, WorkerLimits

_active = ContextVar("worker_accounting", default=None)
_service = ContextVar("worker_service_operation", default=None)
# Only known local/aux-only toolsets skip a service reservation. New plugin
# toolsets are opaque by default, not silently treated as free providers.
_LOCAL_TOOLSETS = frozenset({
    "file", "terminal", "code_execution", "todo", "memory", "skills",
    "clarify", "delegation", "session_search", "vision", "debugging", "cronjob",
})


def current_worker():
    return _active.get()


def worker_run(fn):
    """Bind before preflight/compression and restore even on early returns/errors."""
    @wraps(fn)
    def run(agent, *args, **kwargs):
        limits = getattr(agent, "_worker_limits", None)
        limits = limits if isinstance(limits, WorkerLimits) else None
        token = _active.set(limits)  # A main or unnamed child must NOT inherit its caller's budget.
        try:
            if limits:
                limits.check()
            result = fn(agent, *args, **kwargs)
            if limits and limits.exhausted:
                result.update(completed=False, exit_reason="worker_budget")
                message = limits.failure_message or f"Worker budget exhausted: {limits.exhausted}"
                if message not in str(result.get("final_response", "")):
                    partial = result.get("final_response")
                    result["final_response"] = message + (f"\n\nPartial result:\n{partial}" if partial else "")
            return result
        except WorkerBudgetExceeded as exc:
            return {"completed": False, "exit_reason": "worker_budget", "final_response": str(exc)}
        finally:
            _active.reset(token)
    return run


def record_response(limits, operation, response, *, provider="", api_mode="", model="", base_url=""):
    """Use provider-reported prices first, otherwise the shared model pricing engine."""
    from agent.usage_pricing import normalize_usage, estimate_usage_cost
    if isinstance(response, list):
        # Extraction batches can report one usage/cost bucket per fetched page.
        from agent.usage_pricing import CanonicalUsage
        combined = CanonicalUsage(request_count=0)
        amounts = []
        all_known = bool(response)
        for item in response:
            get_item = item.get if isinstance(item, dict) else lambda k, d=None: getattr(item, k, d)
            raw = get_item("usage")
            if raw is not None:
                try:
                    combined += normalize_usage(raw, provider=provider, api_mode=api_mode)
                except (TypeError, ValueError, OverflowError):
                    pass
            amount = get_item("cost_usd", get_item("cost"))
            if not limits._number(amount):
                all_known = False
            else:
                amounts.append(Decimal(str(amount)))
        response = {
            "usage": {"prompt_tokens": combined.prompt_tokens, "completion_tokens": combined.output_tokens},
            "cost_usd": sum(amounts) if amounts else None, "cost_status": "actual" if all_known else "unknown",
        }
    get = response.get if isinstance(response, dict) else lambda k, d=None: getattr(response, k, d)
    usage = get("usage")
    usage_get = usage.get if isinstance(usage, dict) else lambda k, d=None: getattr(usage, k, d)
    amount = get("cost_usd", get("cost", usage_get("cost", usage_get("cost_usd"))))
    status = get("cost_status", "actual" if amount is not None else "unknown")
    if amount is None and get("estimated_cost_usd") is not None:
        amount, status = get("estimated_cost_usd"), "estimated"
    cost = SimpleNamespace(amount_usd=amount, status=status)
    valid_usage = all(v is not None for v in limits.usage_values(usage, provider=provider, api_mode=api_mode).values())
    if amount is None and valid_usage and model:
        try:
            cost = estimate_usage_cost(
                get("model", model) or model,
                normalize_usage(usage, provider=provider, api_mode=api_mode),
                provider=provider, base_url=str(base_url or ""),
            )
        except Exception:
            pass  # Explicit unknown below; never substitute zero for missing prices.
    limits.complete_operation(operation, usage=usage, cost_result=cost, provider=provider, api_mode=api_mode)


def provider_call(callback, request, *, source, provider="", api_mode="", base_url="", tokens_required=True):
    limits = current_worker()
    if limits is None:
        return callback(request)
    operation = limits.begin_operation(source, request, tokens_required=tokens_required)
    try:
        response = callback(request)
    except BaseException:
        limits.complete_operation(operation)
        raise
    record_response(limits, operation, response, provider=provider, api_mode=api_mode,
                    model=request.get("model", ""), base_url=base_url)
    return response

def fail_on_worker_budget(exc):
    """Do not route a local budget rejection through provider retry/fallback."""
    if isinstance(exc, WorkerBudgetExceeded):
        raise exc



async def provider_call_async(callback, request, **route):
    limits = current_worker()
    if limits is None:
        return await callback(request)
    operation = limits.begin_operation(route.pop("source"), request)
    try:
        response = await callback(request)
    except BaseException:
        limits.complete_operation(operation)
        raise
    record_response(limits, operation, response, model=request.get("model", ""), **route)
    return response


def _begin_service(limits, source):
    with limits._lock:
        reservation = _service.get()
        if reservation and reservation["limits"] is limits and not reservation["used"]:
            reservation["used"] = True
            operation = reservation["operation"]
            limits._operations[operation]["source"] = source
            return operation
        return limits.begin_operation(source, tokens_required=False)


def service_call(callback, request, *, source, capture_receipt=False):
    """Account a real tool-provider response before its handler drops metadata."""
    limits = current_worker()
    if limits is None:
        return callback(request)
    operation = _begin_service(limits, source)
    try:
        response = callback(request)
    except BaseException:
        limits.complete_operation(operation)
        raise
    record_response(limits, operation, response)
    if capture_receipt:
        try:
            response._worker_receipt = (limits, operation)
        except (AttributeError, TypeError, ValueError):
            pass
    return response


def record_service_payload(response, payload):
    """HTTP tools can reveal usage/cost only after reading their response body."""
    receipt = getattr(response, "__dict__", {}).get("_worker_receipt")
    if receipt is not None:
        limits, operation = receipt
        record_response(limits, operation, payload)


async def service_call_async(callback, request, *, source):
    limits = current_worker()
    if limits is None:
        return await callback(request)
    operation = _begin_service(limits, source)
    try:
        response = await callback(request)
    except BaseException:
        limits.complete_operation(operation)
        raise
    record_response(limits, operation, response)
    return response


def provider_stream(callback, request, *, source, **route):
    """Reserve before opening a stream; report its final usage on close/failure."""
    limits = current_worker()
    if limits is None:
        return callback(request)
    operation = limits.begin_operation(source, request)
    try:
        stream = callback(request)
    except BaseException:
        limits.complete_operation(operation)
        raise
    if hasattr(stream, "choices") or isinstance(stream, dict):
        record_response(limits, operation, stream, model=request.get("model", ""), **route)
        return stream

    def chunks():
        usage, model, cost = None, request.get("model", ""), None
        try:
            for chunk in stream:
                usage = getattr(chunk, "usage", None) or usage
                model = getattr(chunk, "model", None) or model
                cost = getattr(chunk, "cost_usd", None) if getattr(chunk, "cost_usd", None) is not None else cost
                yield chunk
        finally:
            try:
                record_response(
                    limits, operation, SimpleNamespace(usage=usage, model=model, cost_usd=cost),
                    model=model, **route,
                )
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
    return chunks()


def tool_call(callback, name, toolset):
    """Catch reported tool-provider costs; local tools only get the admission gate."""
    limits = current_worker()
    if limits is None:
        return callback()
    limits.check()
    if toolset in _LOCAL_TOOLSETS:
        return callback()
    operation = limits.begin_operation(f"tool:{name}", tokens_required=False)
    reservation = {"limits": limits, "operation": operation, "used": False}
    token = _service.set(reservation)
    try:
        result = callback()
        data = result
        if isinstance(result, str):
            try:
                data = json.loads(result)
            except (ValueError, TypeError):
                data = {}
        if not reservation["used"]:
            record_response(limits, operation, data)
        return result
    except BaseException:
        if not reservation["used"]:
            limits.complete_operation(operation)
        raise
    finally:
        _service.reset(token)
