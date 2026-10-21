#!/usr/bin/env python3
"""Opt-in, operator-authenticated external CLI qualification; never runs in CI by default."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHORT_PROMPT = "Reply with exactly OK. Do not use tools, read files, or access the network."
LONG_PROMPT = (
    "Without tools, files or network, generate a numbered list of 10000 distinct "
    "short sentences. Continue generating until explicitly interrupted."
)


class Probe:
    """Retain only protocol counters and numerical usage, never raw wire or text."""

    def __init__(self, drop_usage=False):
        self.drop_usage = drop_usage
        self.methods = []
        self.spawns = 0
        self.processes = []
        self.receipts = []
        self.prompt_ids = set()
        self.prompt_started = threading.Event()
        self.cancel_accepted = False

    def outgoing(self, message):
        method = message.get("method")
        if method:
            self.methods.append(method)
        if method == "session/prompt":
            self.prompt_ids.add(message.get("id"))
            self.prompt_started.set()

    def incoming(self, message):
        if message.get("id") in self.prompt_ids and isinstance(message.get("result"), dict):
            result = message["result"]
            self.cancel_accepted |= result.get("stopReason") in {"cancelled", "canceled"}
            usage = result.get("usage") or {}
            self.receipts.append((
                usage.get("inputTokens", usage.get("input_tokens")),
                usage.get("outputTokens", usage.get("output_tokens")),
            ))
            if self.drop_usage:
                result.pop("usage", None)
        if message.get("method") == "thread/tokenUsage/updated":
            usage = (message.get("params") or {}).get("tokenUsage") or {}
            total = usage.get("total") or {}
            self.receipts.append((total.get("inputTokens"), total.get("outputTokens")))
            if self.drop_usage:
                usage.pop("total", None)
        return message

    def dispatches(self):
        return self.methods.count("session/prompt") + self.methods.count("turn/start")


class WirePipe:
    """Observe ACP stdio in memory without writing transcripts or altering normal traffic."""

    def __init__(self, stream, probe, outbound=False):
        self.stream, self.probe, self.outbound = stream, probe, outbound

    def __getattr__(self, key):
        return getattr(self.stream, key)

    def write(self, text):
        result = self.stream.write(text)
        self.probe.outgoing(json.loads(text))
        return result

    def __iter__(self):
        for line in self.stream:
            yield json.dumps(self.probe.incoming(json.loads(line))) + "\n"


def create_client(transport, command, args, cwd, probe):
    if transport == "acp":
        from agent.copilot_acp_client import CopilotACPClient

        class ObservedACP(CopilotACPClient):
            def _spawn(self):
                proc = super()._spawn()
                probe.spawns += 1
                probe.processes.append(proc)
                proc.stdin = WirePipe(proc.stdin, probe, outbound=True)
                proc.stdout = WirePipe(proc.stdout, probe)
                return proc

        return ObservedACP(acp_command=command, acp_args=args, acp_cwd=str(cwd))

    from agent.transports.codex_app_server import CodexAppServerClient
    from agent.transports.codex_app_server_session import CodexAppServerSession

    class ObservedCodex(CodexAppServerClient):
        def __init__(self, **kwargs):
            super().__init__(codex_bin=command, extra_args=args)
            probe.spawns += 1
            probe.processes.append(self._proc)

        def request(self, method, params=None, **kwargs):
            probe.methods.append(method)
            result = super().request(method, params, **kwargs)
            if method == "turn/start":
                probe.prompt_started.set()
            if method == "turn/interrupt":
                probe.cancel_accepted = True  # A successful JSON-RPC reply, not just a write.
            return result

        def take_notification(self, timeout=0):
            note = super().take_notification(timeout)
            return probe.incoming(note) if note else note

    return CodexAppServerSession(cwd=str(cwd), client_factory=ObservedCodex)


class Worker:
    def __init__(self, transport, client, budget, model, timeout):
        from tools.delegate_worker_limits import WorkerLimits
        self._worker_limits = WorkerLimits({"id": "qualification", "budget": budget}, SimpleNamespace())
        self.transport, self.client, self.model, self.timeout = transport, client, model, timeout

    def run(self, prompt=SHORT_PROMPT):
        from agent.worker_accounting import worker_run
        return worker_run(Worker._run)(self, prompt)

    def _run(self, prompt):
        if self.transport == "acp":
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}], model=self.model, timeout=self.timeout,
            )
            return {"completed": True, "has_text": bool(response.choices[0].message.content)}
        result = self.client.run_turn(prompt, turn_timeout=self.timeout, notification_poll_timeout=0.05)
        return {
            "completed": result.error is None and not result.interrupted,
            "has_text": bool(result.final_text), "interrupted": result.interrupted,
        }


def require(condition, code):
    if not condition:
        raise QualificationFailure(code)


class QualificationFailure(Exception):
    pass


def assert_no_restart(worker, probe):
    before = (probe.spawns, probe.dispatches())
    result = worker.run()
    require(result.get("exit_reason") == "worker_budget", "exhausted_worker_restarted")
    require((probe.spawns, probe.dispatches()) == before, "exhausted_worker_dispatched")


def check_receipts(transport, receipts, snapshot):
    """Codex totals are thread-cumulative; ACP creates one session per prompt."""
    from tools.delegate_worker_limits import WorkerLimits
    require(bool(receipts), "usage_missing")
    require(all(WorkerLimits._number(v, integer=True) for pair in receipts for v in pair), "usage_invalid")
    if transport == "acp":
        inp, out = (sum(pair[i] for pair in receipts) for i in (0, 1))
    else:
        require(all(all(b[i] >= a[i] for i in (0, 1)) for a, b in zip(receipts, receipts[1:])),
                "cumulative_usage_decreased")
        inp, out = receipts[-1]
    require(inp + out > 0, "usage_empty")
    require((snapshot["input_tokens"], snapshot["output_tokens"]) == (inp, out), "usage_miscounted")


def qualify_case(case, transport, command, args, cwd, model=None, timeout=45, duration=8):
    budgets = {
        "usage_and_request_cap": {"max_requests": 2, "max_total_tokens": 1_000_000},
        "token_cap": {"max_total_tokens": 1},
        "missing_usage": {"max_total_tokens": 1_000_000},
        "deadline": {"max_duration_seconds": duration},
        "cancel_acceptance": {"max_duration_seconds": timeout},
        "cost_rejected": {"max_cost_usd": 1},
    }
    probe = Probe(drop_usage=case == "missing_usage")
    client = create_client(transport, command, args, cwd, probe)
    worker = Worker(transport, client, budgets[case], model, timeout)
    # All cases, including the supposedly short prompts, have a wall-clock limit.
    watchdog = threading.Timer(timeout + 5, client.close)
    watchdog.daemon = True
    watchdog.start()
    try:
        if case == "cost_rejected":
            try:
                worker.run()
            except ValueError as exc:
                require("does not expose verifiable USD costs" in str(exc), "wrong_cost_rejection")
                require(probe.spawns == 0, "cost_rejection_spawned_cli")
            else:
                raise QualificationFailure("unobservable_cost_accepted")
        elif case == "usage_and_request_cap":
            for _ in range(2):
                result = worker.run()
                require(result.get("completed") and result.get("has_text"), "prompt_not_completed")
            snapshot = worker._worker_limits.snapshot()
            check_receipts(transport, probe.receipts, snapshot)
            require(snapshot["requests"] == 2 and probe.dispatches() == 2, "request_miscounted")
            assert_no_restart(worker, probe)
        elif case == "cancel_acceptance":
            errors = []

            def run():
                try:
                    worker.run(LONG_PROMPT)
                except Exception:
                    errors.append(True)

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            require(probe.prompt_started.wait(timeout / 2), "prompt_never_started")
            if transport == "acp":
                with client._rpc_write_lock:
                    proc = client._active_process
                    require(proc is not None, "prompt_already_finished")
                    proc.stdin.write(json.dumps({
                        "jsonrpc": "2.0", "method": "session/cancel",
                        "params": {"sessionId": client._active_session_id},
                    }) + "\n")
                    proc.stdin.flush()
            else:
                client.request_interrupt()
            thread.join(timeout / 2)
            require(not thread.is_alive() and not errors and probe.cancel_accepted,
                    "cancellation_not_acknowledged")
        else:
            started = time.monotonic()
            result = worker.run(LONG_PROMPT if case == "deadline" else SHORT_PROMPT)
            require(result.get("exit_reason") == "worker_budget", "budget_not_enforced")
            expected = {"token_cap": "max_total_tokens", "missing_usage": "token_usage",
                        "deadline": "max_duration_seconds"}[case]
            require(worker._worker_limits.exhausted == expected, "wrong_exhaustion_reason")
            if case == "deadline":
                require(time.monotonic() - started <= duration + 5, "deadline_overrun")
                method = "session/cancel" if transport == "acp" else "turn/interrupt"
                require(method in probe.methods, "deadline_did_not_exercise_protocol_cancel")
                require(all(proc.poll() is not None for proc in probe.processes),
                        "deadline_left_process_alive")
            assert_no_restart(worker, probe)
        return {"case": case, "status": "passed", "spawns": probe.spawns,
                "dispatches": probe.dispatches(), "fault_injection": case == "missing_usage"}
    finally:
        watchdog.cancel()
        client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Permit billable real CLI calls")
    parser.add_argument("--operator-authenticated", action="store_true",
                        help="Attest the CLIs use your own pre-authenticated operator account")
    parser.add_argument("--transport", choices=["acp", "codex"], required=True)
    parser.add_argument("--command", help="Installed CLI executable, not a shell command")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--deadline-seconds", type=float, default=8)
    parser.add_argument("--report", type=Path, help="Optional sanitized JSON evidence destination")
    options = parser.parse_args(argv)
    if not options.run_live or not options.operator_authenticated:
        parser.error("Live qualification requires --run-live AND --operator-authenticated; no CLI was started.")
    if not 0 < options.deadline_seconds < options.timeout or options.timeout > 300:
        parser.error("Require 0 < deadline-seconds < timeout <= 300.")
    command = shutil.which(options.command or ("copilot" if options.transport == "acp" else "codex"))
    report = {"schema": 1, "transport": options.transport, "status": "blocked", "checks": [],
              "provenance": "operator-authenticated CLI; not release qualification",
              "billing_guarantee": "Reported consumption thresholds, not prepaid spending caps"}
    # Do not print raw CLI errors, prompts, configuration, stderr, paths or credentials.
    logging.disable(logging.CRITICAL)
    if command is None:
        report["reason"] = "cli_not_installed"
    else:
        try:
            from tools.environments.local import marcel_subprocess_env
            version = subprocess.run(
                [command, "--version"], capture_output=True, text=True, timeout=10,
                env=marcel_subprocess_env(inherit_credentials=True),
            )
            match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?\b", version.stdout)
            require(version.returncode == 0 and match is not None, "cli_version_unavailable")
            report["cli_version"] = match.group()
            args = ["--acp", "--stdio"] if options.transport == "acp" else [
                "-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"',
            ]
            with tempfile.TemporaryDirectory(prefix="marcel-external-qualification-") as cwd:
                for case in ("usage_and_request_cap", "token_cap", "missing_usage", "deadline",
                             "cancel_acceptance", "cost_rejected"):
                    try:
                        report["checks"].append(qualify_case(
                            case, options.transport, command, args, cwd, options.model,
                            options.timeout, options.deadline_seconds,
                        ))
                    except Exception as exc:
                        report["checks"].append({
                            "case": case, "status": "failed",
                            "reason": str(exc) if isinstance(exc, QualificationFailure) else type(exc).__name__,
                        })
            report["status"] = "passed" if all(c["status"] == "passed" for c in report["checks"]) else "failed"
        except Exception as exc:
            report["reason"] = str(exc) if isinstance(exc, QualificationFailure) else type(exc).__name__
    text = json.dumps(report, indent=2)
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
