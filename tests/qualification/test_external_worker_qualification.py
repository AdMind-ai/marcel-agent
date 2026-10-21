"""Offline tests of the opt-in harness, NOT evidence of installed CLI compatibility."""

import json
from pathlib import Path
import sys

import pytest

from scripts.qualification.external_worker_budget import (
    Probe, QualificationFailure, check_receipts, main, qualify_case,
)

PEER = Path(__file__).parents[1] / "fixtures" / "external_budget_peer.py"


@pytest.fixture(params=["acp", "codex"])
def peer(request, tmp_path):
    log = tmp_path / "wire.jsonl"
    if request.param == "acp":
        return request.param, sys.executable, ["normal", str(log)]
    executable = tmp_path / "codex-peer"
    executable.write_text(f"#!{sys.executable}\n" + PEER.read_text())
    executable.chmod(0o700)
    return request.param, str(executable), ["normal", str(log)]


@pytest.mark.parametrize("case", ["usage_and_request_cap", "token_cap", "missing_usage", "cost_rejected"])
def test_harness_checks_contract_through_offline_process(case, peer, tmp_path):
    transport, command, args = peer
    if transport == "acp":
        args = [str(PEER), *args]
    report = qualify_case(case, transport, command, args, tmp_path, timeout=3)
    assert report["status"] == "passed"
    assert report["fault_injection"] is (case == "missing_usage")
    if case == "cost_rejected":
        assert report["spawns"] == report["dispatches"] == 0
    assert "wire" not in report


def test_codex_cumulative_receipts_are_not_summed():
    check_receipts("codex", [(7, 2), (14, 4)], {"input_tokens": 14, "output_tokens": 4})
    with pytest.raises(QualificationFailure, match="usage_miscounted"):
        check_receipts("codex", [(7, 2), (14, 4)], {"input_tokens": 21, "output_tokens": 6})


def test_invalid_missing_and_decreasing_receipts_cannot_qualify():
    for receipts in ([], [(True, 2)], [(None, 2)], [(7, 2), (1, 1)]):
        with pytest.raises(QualificationFailure):
            check_receipts("codex", receipts, {"input_tokens": 7, "output_tokens": 2})


def test_cancellation_notification_is_not_an_acknowledgement():
    probe = Probe()
    probe.outgoing({"method": "session/cancel"})
    assert not probe.cancel_accepted
    probe.outgoing({"method": "session/prompt", "id": 3})
    probe.incoming({"id": 3, "result": {"stopReason": "cancelled"}})
    assert probe.cancel_accepted


def test_probe_does_not_retain_prompts_keys_or_answers():
    probe = Probe()
    probe.outgoing({"id": 1, "method": "session/prompt", "params": {"secret": "DO_NOT_KEEP"}})
    probe.incoming({"id": 1, "result": {"text": "DO_NOT_KEEP", "usage": {"inputTokens": 2, "outputTokens": 1}}})
    assert "DO_NOT_KEEP" not in repr(vars(probe))


def test_no_live_execution_without_both_opt_ins(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *_: pytest.fail("must not resolve or start CLI"))
    for flags in ([], ["--run-live"], ["--operator-authenticated"]):
        with pytest.raises(SystemExit) as exc:
            main(["--transport", "acp", *flags])
        assert exc.value.code == 2


def test_missing_cli_is_blocked_not_passed(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda *_: None)
    assert main(["--transport", "codex", "--run-live", "--operator-authenticated"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert report["reason"] == "cli_not_installed"
    assert report["checks"] == []


def test_deadline_does_not_qualify_when_cancel_never_reached_peer(peer, tmp_path):
    transport, command, args = peer
    args[0] = "handshake_stall"
    if transport == "acp":
        args = [str(PEER), *args]
    with pytest.raises(QualificationFailure, match="deadline_did_not_exercise_protocol_cancel"):
        qualify_case("deadline", transport, command, args, tmp_path, timeout=2, duration=0.25)
