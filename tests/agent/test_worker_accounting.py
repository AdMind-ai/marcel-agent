"""Real accounting/dispatch paths with local provider fixtures (no paid calls)."""

import asyncio
import contextvars
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from agent import worker_accounting as accounting
from tools.delegate_worker_limits import WorkerBudgetExceeded, WorkerLimits


def guard(**budget):
    return WorkerLimits({"id": "review", "budget": budget}, NS())


def response(inp=3, out=2, cost=0.1):
    return NS(usage=NS(prompt_tokens=inp, completion_tokens=out), model="test-model", cost_usd=cost)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    token = accounting._active.set(None)
    try:
        yield
    finally:
        accounting._active.reset(token)


def test_main_and_aux_share_a_ledger_without_session_totals_or_double_hooks():
    limits = guard(max_total_tokens=10, max_cost_usd=1)
    child = NS(_worker_limits=limits, session_total_tokens=100000, session_estimated_cost_usd=999)

    @accounting.worker_run
    def run(agent):
        limits.before_request(agent, {})
        for _ in range(2):  # response-check hook and turn-usage hook
            limits.observe_completed_attempt({"prompt_tokens": 3, "completion_tokens": 2})
            limits.observe_cost(NS(amount_usd=Decimal("0.1"), status="actual"))
        accounting.provider_call(lambda _: response(), {}, source="compression")
        with pytest.raises(WorkerBudgetExceeded, match="max_total_tokens"):
            accounting.tool_call(lambda: pytest.fail("must not run"), "read_file", "file")
        return {"completed": True}

    result = run(child)
    assert result["exit_reason"] == "worker_budget"
    assert limits.snapshot()["total_tokens"] == 10
    assert limits.snapshot()["cost_usd"] == pytest.approx(0.2)
    assert limits.requests == 2


def test_real_auxiliary_sync_chokepoint_and_output_cap():
    from agent.auxiliary_client import _relay_sync_completion
    limits = guard(max_output_tokens=2)
    create = Mock(return_value=response())
    client = NS(chat=NS(completions=NS(create=create)), base_url="https://provider.invalid/v1")

    @accounting.worker_run
    def run(agent):
        _relay_sync_completion(client, {"model": "test-model", "max_tokens": 100}, provider="openai")
        return _relay_sync_completion(client, {"model": "test-model"}, provider="openai")

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    create.assert_called_once_with(model="test-model", max_tokens=2)
    assert limits.snapshot()["total_tokens"] == 5


def test_compression_progress_path_counts_each_physical_retry(monkeypatch):
    from agent import auxiliary_client as aux
    limits = guard(max_requests=2)
    create = Mock(side_effect=[RuntimeError("stream rejected"), response()])
    client = NS(chat=NS(completions=NS(create=create)), base_url="https://provider.invalid/v1")
    monkeypatch.setattr(aux, "_aux_progress_active", lambda: True)
    monkeypatch.setattr(aux, "_client_streams_internally", lambda _: False)

    @accounting.worker_run
    def run(agent):
        result = aux._create_with_progress_once(client, {"model": "test-model"}, "compression")
        return {"completed": True, "text": result.model}

    assert run(NS(_worker_limits=limits))["completed"]
    assert create.call_count == limits.requests == 2
    # The rejected attempt has no verifiable invoice.
    assert limits.snapshot()["cost_status"] == "unknown"


def test_aux_retry_cannot_dispatch_after_missing_cost(monkeypatch):
    from agent import auxiliary_client as aux
    limits = guard(max_cost_usd=1)
    create = Mock(side_effect=[RuntimeError("stream rejected"), response()])
    client = NS(chat=NS(completions=NS(create=create)), base_url="")
    monkeypatch.setattr(aux, "_aux_progress_active", lambda: True)
    monkeypatch.setattr(aux, "_client_streams_internally", lambda _: False)

    @accounting.worker_run
    def run(agent):
        return aux._create_with_progress_once(client, {"model": "test-model"}, "compression")

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    assert create.call_count == limits.requests == 1


def test_async_auxiliary_chokepoint_shares_the_sync_budget():
    from agent.auxiliary_client import _relay_async_completion
    limits = guard(max_requests=2)
    seen = []

    async def create(**kwargs):
        seen.append(kwargs)
        return response()

    client = NS(chat=NS(completions=NS(create=create)), base_url="")

    @accounting.worker_run
    def run(agent):
        accounting.provider_call(lambda _: response(), {}, source="compression")
        asyncio.run(_relay_async_completion(client, {"model": "test-model"}, provider="openai"))
        return asyncio.run(_relay_async_completion(client, {"model": "test-model"}, provider="openai"))

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    assert len(seen) == 1 and limits.requests == 2


def test_stream_usage_is_counted_once_and_closed():
    from agent.auxiliary_client import _relay_sync_stream
    limits = guard(max_total_tokens=5)

    class Stream:
        closed = False

        def __iter__(self):
            yield NS(model="test-model", usage=None)
            yield response()

        def close(self):
            self.closed = True

    stream = Stream()
    client = NS(chat=NS(completions=NS(create=lambda **kw: stream)), base_url="")

    @accounting.worker_run
    def run(agent):
        assert len(list(_relay_sync_stream(client, {"model": "test-model"}, provider="openai"))) == 2
        limits.check()
        return {"completed": True}

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    assert limits.snapshot()["total_tokens"] == 5 and limits.requests == 1
    assert stream.closed


def test_registry_services_record_before_handler_discards_provider_metadata():
    from tools.registry import ToolRegistry
    limits = guard(max_cost_usd=0.2)
    registry = ToolRegistry()
    calls = []

    def handler(args, **kwargs):
        data = accounting.service_call(
            lambda request: calls.append(request) or {"cost_usd": 0.2, "images": ["image"]},
            args, source="image:fixture",
        )
        return json.dumps({"images": data["images"]})  # billing fields intentionally stripped

    registry.register("image_fixture", "image_gen", {"name": "image_fixture"}, handler)

    @accounting.worker_run
    def run(agent):
        assert json.loads(registry.dispatch("image_fixture", {})) == {"images": ["image"]}
        assert "error" in json.loads(registry.dispatch("image_fixture", {}))
        return {"completed": True}

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    assert len(calls) == limits.requests == 1
    assert limits.snapshot()["cost_usd"] == 0.2
    assert limits.snapshot()["unmeasurable_operations"] == []


def test_multiple_services_inside_tool_stop_before_second_charge():
    from tools.registry import ToolRegistry
    limits = guard(max_requests=1)
    registry = ToolRegistry()
    called = []

    def handler(args, **kwargs):
        for i in range(2):
            accounting.service_call(
                lambda request: called.append(request) or {"cost_usd": 0}, {"i": i}, source="image:fixture",
            )
        return "{}"

    registry.register("fixture", "image_gen", {"name": "fixture"}, handler)

    @accounting.worker_run
    def run(agent):
        registry.dispatch("fixture", {})
        return {"completed": True}

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    assert called == [{"i": 0}]


@pytest.mark.parametrize("amount", [None, float("nan"), -1, True])
def test_unmeasurable_service_cost_is_explicit_and_blocks_all_later_operations(amount):
    limits = guard(max_cost_usd=1)

    @accounting.worker_run
    def run(agent):
        accounting.tool_call(lambda: json.dumps({"cost_usd": amount}), "remote", "mcp-fixture")
        assert limits.snapshot()["unmeasurable_operations"] == ["tool:remote"]
        accounting.provider_call(lambda _: pytest.fail("must not dispatch"), {}, source="vision")

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    assert limits.requests == 1


def test_missing_auxiliary_usage_never_becomes_a_zero_cost_estimate(monkeypatch):
    from agent import usage_pricing
    estimate = Mock(return_value=NS(amount_usd=0, status="estimated"))
    monkeypatch.setattr(usage_pricing, "estimate_usage_cost", estimate)
    limits = guard(max_cost_usd=1)

    @accounting.worker_run
    def run(agent):
        accounting.provider_call(lambda _: NS(model="test-model", usage={}), {"model": "test-model"}, source="compression")
        limits.check()

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    estimate.assert_not_called()


def test_provider_invoice_does_not_require_tokens_when_only_cost_is_limited():
    limits = guard(max_cost_usd=1)

    @accounting.worker_run
    def run(agent):
        accounting.provider_call(lambda _: {"cost_usd": 0.1}, {}, source="auxiliary")
        accounting.tool_call(lambda: "ok", "read_file", "file")
        return {"completed": True}

    assert run(NS(_worker_limits=limits))["completed"]
    assert limits.snapshot()["cost_usd"] == 0.1


def test_context_is_restored_after_exception_and_main_or_unnamed_child_never_pays_worker():
    limits = guard(max_requests=1)
    other = guard(max_requests=5)

    @accounting.worker_run
    def inner(agent):
        accounting.provider_call(lambda _: response(), {}, source="compression")
        return {"completed": True}

    @accounting.worker_run
    def outer(agent):
        inner(NS())  # main/unnamed child clears ambient worker budget
        inner(NS(_worker_limits=other))
        assert accounting.current_worker() is limits
        raise ValueError("fixture")

    with pytest.raises(ValueError, match="fixture"):
        outer(NS(_worker_limits=limits))
    assert limits.requests == 0 and other.requests == 1
    assert accounting.current_worker() is None


def test_atomic_concurrent_request_reservations_never_exceed_cap():
    limits = guard(max_requests=3)
    barrier = threading.Barrier(12)
    accepted = []

    @accounting.worker_run
    def run(agent):
        def work():
            barrier.wait()
            try:
                op = limits.begin_operation("parallel")
            except WorkerBudgetExceeded:
                return
            accepted.append(op)
            limits.complete_operation(op, usage={"prompt_tokens": 1, "completion_tokens": 1},
                                      cost_result=NS(amount_usd=0.1, status="actual"))

        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(contextvars.copy_context().run, work) for _ in range(12)]
            for future in futures:
                future.result(timeout=5)
        return {"completed": True}

    run(NS(_worker_limits=limits))
    assert len(set(accepted)) == limits.requests == 3
    assert limits.snapshot()["total_tokens"] == 6
    assert limits.snapshot()["cost_usd"] == pytest.approx(0.3)


def test_concurrent_inflight_receipts_are_all_counted_but_later_dispatches_stop():
    limits = guard(max_cost_usd=0.1)
    first, second = limits.begin_operation("first"), limits.begin_operation("second")
    limits.complete_operation(first, cost_result=NS(amount_usd=0.1, status="actual"))
    with pytest.raises(WorkerBudgetExceeded):
        limits.begin_operation("third")
    limits.complete_operation(second, cost_result=NS(amount_usd=0.2, status="actual"))
    assert limits.requests == 2
    assert limits.snapshot()["cost_usd"] == pytest.approx(0.3)


def test_delegation_result_exposes_auxiliary_and_service_totals_and_unknowns():
    from tools.delegate_tool_child_run import _build_result_entry
    limits = guard()
    op = limits.begin_operation("image", tokens_required=False)
    limits.complete_operation(op)
    child = NS(_worker_limits=limits, session_estimated_cost_usd=999)
    entry = _build_result_entry(
        child, {"completed": True, "final_response": "done"}, 0, 0,
        NS(schema=None, valid=None, errors=[], retries=0),
    )
    assert entry["budget_usage"]["requests"] == 1
    assert entry["cost_usd"] == 0
    assert entry["cost_status"] == "unknown"
    assert entry["budget_usage"]["unmeasurable_operations"] == ["image"]


def test_service_http_body_receipt_updates_the_same_operation():
    limits = guard(max_cost_usd=0.1)

    @accounting.worker_run
    def run(agent):
        def tool():
            http_response = accounting.service_call(
                lambda _: NS(), {}, source="tts:http", capture_receipt=True,
            )
            accounting.record_service_payload(http_response, {"cost_usd": 0.1})
            return json.dumps({"file": "audio.wav"})
        accounting.tool_call(tool, "text_to_speech", "tts")
        limits.check()

    result = run(NS(_worker_limits=limits))
    assert result["exit_reason"] == "worker_budget"
    assert "exhausted" in result["final_response"]
    assert limits.requests == 1
    assert limits.snapshot()["cost_usd"] == 0.1
    assert not limits.snapshot()["unmeasurable_operations"]


def test_partial_batch_cost_remains_visible_but_cannot_verify_budget():
    limits = guard(max_cost_usd=1)

    @accounting.worker_run
    def run(agent):
        accounting.service_call(lambda _: [{"cost_usd": 0.1}, {"error": "no metadata"}],
                                [], source="web_extract")
        limits.check()

    result = run(NS(_worker_limits=limits))
    assert "cannot be verified" in result["final_response"]
    assert limits.snapshot()["cost_usd"] == 0.1
    assert limits.snapshot()["cost_status"] == "unknown"


def test_named_workers_under_one_parent_have_independent_run_receipts():
    parent = NS(session_estimated_cost_usd=1000)
    first = WorkerLimits({"id": "one", "budget": {"max_requests": 2}}, parent)
    second = WorkerLimits({"id": "two", "budget": {"max_requests": 2}}, parent)
    barrier = threading.Barrier(2)

    @accounting.worker_run
    def run(agent):
        def create(_):
            barrier.wait(timeout=5)
            return response(cost=agent.cost)
        accounting.provider_call(create, {}, source="compression")
        return {"completed": True}

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(run, NS(_worker_limits=first, cost=0.1))
        b = pool.submit(run, NS(_worker_limits=second, cost=0.2))
        assert a.result()["completed"] and b.result()["completed"]
    assert first.requests == second.requests == 1
    assert first.snapshot()["cost_usd"] == 0.1
    assert second.snapshot()["cost_usd"] == 0.2
    assert parent.session_estimated_cost_usd == 1000
    assert accounting.current_worker() is None


def test_new_provider_plugin_toolsets_are_not_assumed_free():
    limits = guard(max_cost_usd=0.1)

    @accounting.worker_run
    def run(agent):
        accounting.tool_call(lambda: json.dumps({"cost_usd": 0.1}), "provider_tool", "custom_service")
        accounting.tool_call(lambda: pytest.fail("must not dispatch"), "read_file", "file")

    assert run(NS(_worker_limits=limits))["exit_reason"] == "worker_budget"
    assert limits.requests == 1 and limits.snapshot()["cost_usd"] == 0.1
