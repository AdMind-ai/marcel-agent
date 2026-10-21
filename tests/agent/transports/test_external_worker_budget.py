"""Budget enforcement through the real ACP/Codex subprocess and worker paths."""

import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from agent.copilot_acp_client import CopilotACPClient
from agent.transports.codex_app_server import CodexAppServerClient
from agent.transports.codex_app_server_session import CodexAppServerSession
from agent.worker_accounting import worker_run, provider_call
from tools.delegate_worker_limits import WorkerLimits

PEER = Path(__file__).parents[2] / "fixtures" / "external_budget_peer.py"


class ExternalWorker:
    def __init__(self, transport, budget, tmp_path, scenario="normal"):
        self._worker_limits = WorkerLimits({"id": "external", "budget": budget}, SimpleNamespace())
        self.log = tmp_path / "wire.jsonl"
        self.clients = []
        self.transport = transport
        if transport == "acp":
            self.client = CopilotACPClient(
                acp_command=sys.executable, acp_args=[str(PEER), scenario, str(self.log)],
                acp_cwd=str(tmp_path),
            )
        else:
            executable = tmp_path / "codex-peer"
            executable.write_text(f"#!{sys.executable}\n" + PEER.read_text())
            executable.chmod(0o700)
            def client_factory(**kwargs):
                client = CodexAppServerClient(
                    codex_bin=str(executable), extra_args=[scenario, str(self.log)],
                )
                self.clients.append(client)
                return client
            self.client = CodexAppServerSession(cwd=str(tmp_path), client_factory=client_factory)

    @worker_run
    def run_conversation(self, text="hello"):
        if self.transport == "acp":
            # Same reservation/receipt path as the local API retry loop.
            self._worker_limits.before_request(self, {})
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": text}], timeout=2,
            )
            self._worker_limits.observe_completed_attempt(response.usage)
            return {"completed": True, "final_response": response.choices[0].message.content}
        result = self.client.run_turn(text, turn_timeout=2, notification_poll_timeout=0.01)
        return {"completed": result.error is None, "final_response": result.final_text}

    def messages(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def close(self):
        self.client.close()


@pytest.fixture(params=["acp", "codex_app_server"])
def transport(request):
    return request.param


def test_last_admitted_request_finishes_then_next_dispatch_is_refused(transport, tmp_path):
    worker = ExternalWorker(transport, {"max_requests": 1}, tmp_path)
    try:
        assert worker.run_conversation()["completed"]
        refused = worker.run_conversation()
        assert refused["exit_reason"] == "worker_budget"
        assert "max_requests" in refused["final_response"]
        methods = [m["method"] for m in worker.messages()]
        assert methods.count("session/prompt" if transport == "acp" else "turn/start") == 1
        assert worker._worker_limits.requests == 1
    finally:
        worker.close()


@pytest.mark.parametrize("scenario", ["stall", "handshake_stall"])
def test_duration_stops_real_process_even_when_peer_never_finishes(transport, tmp_path, scenario, monkeypatch):
    from agent.transports import worker_budget

    cancel_flushed = threading.Event()
    cancel_process = worker_budget.cancel_external_process

    def observe_cancel(send_cancel, close):
        def send_and_record():
            send_cancel()
            cancel_flushed.set()
        return cancel_process(send_and_record, close)

    if transport == "acp":
        monkeypatch.setattr(worker_budget, "cancel_external_process", observe_cancel)
    worker = ExternalWorker(transport, {"max_duration_seconds": 0.25}, tmp_path, scenario)
    start = time.monotonic()
    try:
        result = worker.run_conversation()
        assert not result["completed"]
        assert result["exit_reason"] == "worker_budget"
        assert "max_duration_seconds" in result["final_response"]
        assert time.monotonic() - start < 1.5  # Not the 10-30s handshake/request timeout.
        if transport == "acp":
            assert worker.client._active_process is None
        else:
            assert all(not client.is_alive() for client in worker.clients), [
                (client._closed, client._proc.poll(), worker.client._closed, result)
                for client in worker.clients
            ]
        if scenario == "stall":
            methods = [m["method"] for m in worker.messages()]
            if transport == "acp":
                # The deadline can kill the peer before it logs a flushed
                # notification. Sending is not backend acknowledgement:
                # the separate qualification probe requires a cancelled reply.
                if "session/prompt" in methods:
                    assert cancel_flushed.is_set()
            else:
                assert "turn/interrupt" in methods
    finally:
        worker.close()


@pytest.mark.parametrize("field,threshold", [
    ("max_input_tokens", 7), ("max_output_tokens", 2), ("max_total_tokens", 9),
])
def test_reported_tokens_enforce_threshold_without_last_call_undercount(transport, tmp_path, field, threshold):
    worker = ExternalWorker(transport, {field: threshold}, tmp_path)
    try:
        result = worker.run_conversation()
        assert result["exit_reason"] == "worker_budget"
        assert field in result["final_response"]
        usage = worker._worker_limits.snapshot()
        assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (7, 2, 9)
        assert usage["requests"] == 1
        assert not worker.run_conversation()["completed"]
    finally:
        worker.close()


def test_usage_is_per_turn_not_cumulative_or_double_charged(transport, tmp_path):
    worker = ExternalWorker(transport, {"max_total_tokens": 100, "max_requests": 3}, tmp_path)
    try:
        assert worker.run_conversation()["completed"]
        assert worker.run_conversation()["completed"]
        usage = worker._worker_limits.snapshot()
        assert usage["requests"] == 2
        assert usage["total_tokens"] == 18
        assert usage["cost_status"] == "unknown"
    finally:
        worker.close()


@pytest.mark.parametrize("scenario", ["missing", "malformed"])
def test_unobservable_tokens_fail_closed_instead_of_synthetic_zero(transport, tmp_path, scenario):
    worker = ExternalWorker(transport, {"max_total_tokens": 100}, tmp_path, scenario)
    try:
        result = worker.run_conversation()
        assert result["exit_reason"] == "worker_budget"
        assert "usage unavailable" in result["final_response"]
        assert not worker.run_conversation()["completed"]
    finally:
        worker.close()


def test_decreasing_codex_total_does_not_reuse_previous_valid_receipt(tmp_path):
    worker = ExternalWorker("codex_app_server", {"max_total_tokens": 100}, tmp_path, "decreasing")
    try:
        result = worker.run_conversation()
        assert result["exit_reason"] == "worker_budget"
        assert "usage unavailable" in result["final_response"]
    finally:
        worker.close()


def test_cost_budget_is_refused_before_starting_process(transport, tmp_path):
    worker = ExternalWorker(transport, {"max_cost_usd": 1}, tmp_path)
    try:
        with pytest.raises(ValueError, match="does not expose verifiable USD costs"):
            worker.run_conversation()
        assert not worker.log.exists()
    finally:
        worker.close()


def test_auxiliary_acp_call_borrows_provider_reservation(tmp_path):
    worker = ExternalWorker("acp", {"max_requests": 1}, tmp_path)

    @worker_run
    def auxiliary(agent):
        response = provider_call(
            lambda req: agent.client.chat.completions.create(**req),
            {"messages": [{"role": "user", "content": "hi"}]},
            source="auxiliary:test",
        )
        return {"completed": True, "final_response": response.choices[0].message.content}

    try:
        assert auxiliary(worker)["completed"]
        assert worker._worker_limits.requests == 1
    finally:
        worker.close()


def test_duration_cancels_even_when_prompt_write_is_blocked(transport, tmp_path):
    worker = ExternalWorker(transport, {"max_duration_seconds": 0.25}, tmp_path, "prompt_unread")
    start = time.monotonic()
    try:
        result = worker.run_conversation("x" * 1_000_000)
        assert result["exit_reason"] == "worker_budget"
        assert time.monotonic() - start < 1.5
        if transport == "acp":
            assert worker.client._active_process is None
        else:
            assert all(not client.is_alive() for client in worker.clients)
    finally:
        worker.close()
