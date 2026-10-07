"""Runtime tests for worker budgets, admission and execution permissions."""

from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest

from tools.delegate_worker_limits import WorkerLimits, WorkerBudgetExceeded, constrain_worker_tools
from tools.delegate_worker_registry import parse_workers


def limits(budget=None, **kwargs):
    parent = SimpleNamespace()
    config = parse_workers({"review": {"budget": budget or {}, **kwargs}})["review"]
    return WorkerLimits(config, parent)


def test_requests_count_attempts_not_just_successes_and_no_extra_call_is_allowed():
    guard = limits({"max_requests": 2})
    child = SimpleNamespace()
    guard.before_request(child, {})
    guard.before_request(child, {})
    with pytest.raises(WorkerBudgetExceeded, match="max_requests"):
        guard.before_request(child, {})
    assert guard.requests == 2


@pytest.mark.parametrize("field,counter", [
    ("max_input_tokens", "session_input_tokens"),
    ("max_output_tokens", "session_output_tokens"),
    ("max_total_tokens", "session_total_tokens"),
    ("max_cost_usd", "session_estimated_cost_usd"),
])
def test_reported_usage_threshold_stops_next_request(field, counter):
    guard = limits({field: 10})
    child = SimpleNamespace(**{counter: 10})
    with pytest.raises(WorkerBudgetExceeded, match=field):
        guard.before_request(child, {})
    assert guard.requests == 0


def test_missing_provider_usage_fails_closed_after_first_request():
    guard = limits({"max_total_tokens": 100})
    child = SimpleNamespace()
    guard.before_request(child, {"max_tokens": 1000})
    with pytest.raises(WorkerBudgetExceeded, match="usage unavailable"):
        guard.before_request(child, {})


def test_output_cap_and_duration():
    guard = limits({"max_output_tokens": 15, "max_duration_seconds": 5}, timeout_seconds=30)
    payload = {"max_completion_tokens": 100}
    guard.before_request(SimpleNamespace(), payload)
    assert payload["max_completion_tokens"] == 15
    assert guard.deadline(300) == 5
    guard.observe_completed_attempt({"prompt_tokens": 1, "completion_tokens": 0})
    guard.started -= 10
    with pytest.raises(WorkerBudgetExceeded, match="max_duration_seconds"):
        guard.before_request(SimpleNamespace(session_total_tokens=1), {})


def test_worker_admission_shared_across_dispatches_but_not_other_workers_or_parents():
    parent = SimpleNamespace()
    config = parse_workers({"review": {"max_concurrency": 1}})["review"]
    a, b = WorkerLimits(config, parent), WorkerLimits(config, parent)
    assert a.admission is b.admission
    assert a.admission.acquire(blocking=False)
    assert not b.admission.acquire(blocking=False)
    other = WorkerLimits({**config, "id": "writer"}, parent)
    assert other.admission.acquire(blocking=False)
    a.admission.release()
    assert b.admission.acquire(blocking=False)
    b.admission.release()
    other.admission.release()


def test_selected_permissions_do_not_inherit_mcp_or_role_grants(monkeypatch):
    from tools.delegate_tool_toolsets import _resolve_child_toolsets
    monkeypatch.setattr("tools.delegate_tool_toolsets._get_inherit_mcp_toolsets", lambda: True)
    parent = SimpleNamespace(enabled_toolsets=["file", "web", "mcp-private"], disabled_toolsets=[])
    enabled, disabled = _resolve_child_toolsets(parent, ["file"], "orchestrator", strict=True)
    assert enabled == ["file"] and "delegation" in disabled
    enabled, _ = _resolve_child_toolsets(parent, [], "leaf", strict=True)
    assert enabled == []


def test_execution_allowlist_blocks_even_if_tool_schema_refresh_reintroduces_tool(monkeypatch):
    from agent import tool_executor
    child = SimpleNamespace(valid_tool_names={"read_file", "terminal"},
                            tools=[{"function": {"name": name}} for name in ("read_file", "terminal")])
    constrain_worker_tools(child, {"permissions": "selected", "tools": ["read_file"]})
    assert child.valid_tool_names == {"read_file"}
    # Simulate a later schema refresh. The retained execution policy is still authoritative.
    child.valid_tool_names.add("terminal")
    ref = SimpleNamespace(name="terminal", args={}, trace=[])
    state = SimpleNamespace(blocked=False)
    execute = Mock()
    monkeypatch.setattr(tool_executor, "_blocked_tool_result", lambda *a, **kw: {"error": kw["block_message"]})
    result = tool_executor._dispatch_authorized_once(
        child, state, ref, execute=execute, scope_block=None, display_index=None,
        begin_execution=None, authorization_gate=None,
    )
    assert "not permitted" in result["error"] and state.blocked
    execute.assert_not_called()


def test_retry_loop_checks_budget_before_every_attempt_and_stops_without_dispatch(monkeypatch):
    from agent import conversation_loop
    from types import SimpleNamespace as NS
    child = NS(_worker_limits=limits({"max_requests": 1}))
    state = NS(retry_count=0, max_retries=4, api_kwargs={}, messages=[], api_call_count=0)
    performed = []

    def phase(fn, agent, state, **kwargs):
        if fn.__name__ == "perform_api_call":
            performed.append(1)
            state.retry_count += 1  # a provider failure/retry, not a successful call
        return NS(action="continue", result=None)

    monkeypatch.setattr(conversation_loop, "_run_phase", phase)
    result = conversation_loop._run_api_retry_loop(child, state)
    assert len(performed) == 1
    assert result["exit_reason"] == "worker_budget" and not result["completed"]
    assert child._worker_limits.requests == 1


def test_child_runtime_timeout_and_shared_slot_release(monkeypatch):
    from tools.delegate_tool_child_run import _ChildRun
    monkeypatch.setattr("tools.delegate_tool._get_child_timeout", lambda: 999)
    child = SimpleNamespace(session_id="test-worker", run_conversation=lambda **kw: {"completed": True})
    child._worker_limits = limits({"max_duration_seconds": 1}, max_concurrency=1)
    run = _ChildRun(child, SimpleNamespace(), 0, "Review", None, None)
    result, error, deferred = run.await_child()
    assert result["completed"] and error is None and not deferred
    assert child._worker_limits.admission.acquire(blocking=False)
    child._worker_limits.admission.release()


def test_dispatch_attaches_saved_worker_limits_and_ignores_caller_iteration_override(monkeypatch):
    import json
    from tools import delegate_tool as delegate
    from marcel_cli.setup_marcel import normalize_worker
    worker = normalize_worker({
        "name": "review", "activity": "coding", "model": "chat",
        "permissions": "selected", "toolsets": ["file"], "concurrency": 1,
        "max_iterations": 7, "budget": {"max_requests": 2, "max_duration_seconds": 30},
    })
    monkeypatch.setattr(delegate, "_load_config", lambda: {"workers": {"review": worker}})
    parent = SimpleNamespace(_delegate_depth=0, _interrupt_requested=False, enabled_toolsets=["file"],
                             request_overrides={}, api_mode="chat_completions")
    child = SimpleNamespace(valid_tool_names={"read_file"}, tools=[{"function": {"name": "read_file"}}])
    construction = Mock(return_value=child)
    monkeypatch.setattr(delegate, "_build_child_preserving_parent_tools", construction)
    monkeypatch.setattr(delegate, "_announce_batch", lambda *a: None)
    monkeypatch.setattr("tools.delegation_live_log.create_live_transcripts", lambda *a, **kw: (None, [], []))
    monkeypatch.setattr(delegate, "_run_batch", lambda *a: json.dumps({"ok": True}))
    result = delegate.delegate_task(goal="review", worker="review", max_iterations=1000, parent_agent=parent)
    assert json.loads(result)["ok"]
    assert construction.call_args.kwargs["max_iterations"] == 7
    assert construction.call_args.kwargs["strict_worker_permissions"] is True
    assert child._worker_limits.budget == {"max_requests": 2, "max_duration_seconds": 30}
    assert child._worker_allowed_tools == frozenset({"read_file"})


def test_budget_exhaustion_is_not_reported_as_success():
    from tools.delegate_tool_child_run import _build_result_entry
    child = SimpleNamespace()
    result = {"completed": False, "exit_reason": "worker_budget",
              "final_response": "Worker budget exhausted: max_requests", "api_calls": 2}
    schema = SimpleNamespace(schema=None, valid=None, errors=[], retries=0)
    entry = _build_result_entry(child, result, 0, 0, schema)
    assert entry["status"] == "failed" and entry["exit_reason"] == "worker_budget"
    assert entry["truncated"] is True


@pytest.mark.parametrize("global_timeout,worker_timeout,duration,expected", [
    (10, 60, 120, 10),
    (10, 0, None, 10),
    (0, 5, 20, 5),
    (None, 0, 3, 3),
    (0, 0, None, None),
])
def test_worker_timeout_cannot_raise_or_disable_global_ceiling(
    global_timeout, worker_timeout, duration, expected,
):
    guard = limits({"max_duration_seconds": duration} if duration else {}, timeout_seconds=worker_timeout)
    assert guard.deadline(global_timeout) == expected


@pytest.mark.parametrize("budget_field", [
    "max_input_tokens", "max_output_tokens", "max_total_tokens", "max_cost_usd",
])
def test_real_usage_accounting_valid_then_missing_never_reuses_stale_totals(monkeypatch, budget_field):
    from decimal import Decimal
    from agent import turn_usage
    guard = limits({budget_field: 100})
    counters = {name: 0 for name in (
        "session_api_calls", "session_prompt_tokens", "session_completion_tokens",
        "session_total_tokens", "session_input_tokens", "session_output_tokens",
        "session_cache_read_tokens", "session_cache_write_tokens", "session_reasoning_tokens",
        "session_estimated_cost_usd",
    )}
    child = SimpleNamespace(
        **counters, _worker_limits=guard, provider="openai", api_mode="chat_completions",
        model="gpt-test", base_url="", client=None, session_id="worker-reporting",
        _session_db=None, verbose_logging=False, session_cost_status="unknown",
        context_compressor=SimpleNamespace(
            threshold_tokens=0, _context_probed=False, _verify_compaction_cleared_threshold=False,
            awaiting_real_usage_after_compression=False, update_from_response=Mock(),
        ),
    )
    monkeypatch.setattr(turn_usage, "estimate_usage_cost", lambda *a, **kw: SimpleNamespace(
        amount_usd=Decimal("0.001"), status="estimated", source="test",
    ))
    args = dict(messages=[], api_call_count=1, api_duration=0,
                compression_attempts=0, max_compression_attempts=3)
    guard.before_request(child, {})
    turn_usage.record_response_usage(
        child, SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)), **args,
    )
    guard.before_request(child, {})  # current usage + Decimal cost permit the next dispatch
    old_total, old_cost = child.session_total_tokens, child.session_estimated_cost_usd
    turn_usage.record_response_usage(child, SimpleNamespace(usage=None), **args)
    assert child.session_total_tokens == old_total > 0
    assert child.session_estimated_cost_usd == old_cost > 0
    assert child.session_cost_status == "estimated"  # deliberately stale but not authoritative
    with pytest.raises(WorkerBudgetExceeded, match="cannot be verified"):
        guard.before_request(child, {})
    assert guard.requests == 2


def test_missing_pricing_after_valid_estimate_cannot_use_prior_cost_status():
    from decimal import Decimal
    guard = limits({"max_cost_usd": 1})
    child = SimpleNamespace(session_estimated_cost_usd=0.1, session_cost_status="estimated")
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    guard.before_request(child, {})
    guard.observe_completed_attempt(usage)
    guard.observe_cost(SimpleNamespace(amount_usd=Decimal("0.1"), status="estimated"))
    guard.before_request(child, {})
    guard.observe_completed_attempt(usage)
    guard.observe_cost(SimpleNamespace(amount_usd=None, status="unknown"))
    with pytest.raises(WorkerBudgetExceeded, match="cost estimate unavailable"):
        guard.before_request(child, {})


def test_token_reporting_checks_each_required_bucket_and_accepts_reported_zero():
    guard = limits({"max_input_tokens": 100, "max_output_tokens": 100})
    child = SimpleNamespace(session_input_tokens=1, session_output_tokens=0)
    guard.before_request(child, {})
    guard.observe_completed_attempt({"prompt_tokens": 1, "completion_tokens": 0})
    guard.before_request(child, {})
    guard.observe_completed_attempt({"completion_tokens": 1})
    with pytest.raises(WorkerBudgetExceeded, match="usage unavailable"):
        guard.before_request(child, {})
