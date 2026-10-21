"""Named-worker dispatch through real AIAgent and external stdio transports."""

import json
from pathlib import Path
import sys

import pytest

from run_agent import AIAgent
from tools import delegate_tool
from agent.transports.codex_app_server import CodexAppServerClient

PEER = Path(__file__).parents[1] / "fixtures" / "external_budget_peer.py"


@pytest.fixture(params=["acp", "codex_app_server"])
def external_parent(request, tmp_path, monkeypatch):
    wire_log = tmp_path / "wire.jsonl"
    processes = []
    if request.param == "acp":
        parent = AIAgent(
            model="copilot-acp", provider="copilot-acp", api_mode="chat_completions",
            api_key="stub", base_url="acp://copilot",
            acp_command=sys.executable, acp_args=[str(PEER), "normal", str(wire_log)],
            quiet_mode=True, skip_context_files=True, skip_memory=True, enabled_toolsets=[],
        )
    else:
        peer = tmp_path / "codex-peer"
        peer.write_text(f"#!{sys.executable}\n" + PEER.read_text())
        peer.chmod(0o700)

        def spawn(**kwargs):
            client = CodexAppServerClient(codex_bin=str(peer), extra_args=["normal", str(wire_log)])
            processes.append(client)
            return client

        monkeypatch.setattr("agent.transports.codex_app_server_session.CodexAppServerClient", spawn)
        parent = AIAgent(
            model="test-model", provider="openai", api_mode="codex_app_server",
            api_key="stub", base_url="https://stub.invalid",
            quiet_mode=True, skip_context_files=True, skip_memory=True, enabled_toolsets=[],
        )
    try:
        yield parent, wire_log
    finally:
        parent.close()
        for client in processes:
            client.close()


def worker_config(budget):
    return {"workers": {"external": {
        "permissions": "selected", "toolsets": ["file"], "max_iterations": 2, "budget": budget,
    }}}


def test_saved_budget_is_enforced_by_real_delegation(external_parent, monkeypatch):
    parent, log = external_parent
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: worker_config({"max_requests": 1}))
    result = json.loads(delegate_tool.delegate_task(goal="Say done.", worker="external", parent_agent=parent))
    assert result["results"][0]["status"] == "completed", result
    assert result["results"][0]["budget_usage"]["requests"] == 1
    assert log.exists()


def test_saved_token_budget_produces_failed_delegation_not_success(external_parent, monkeypatch):
    parent, log = external_parent
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: worker_config({"max_total_tokens": 9}))
    result = json.loads(delegate_tool.delegate_task(goal="Say done.", worker="external", parent_agent=parent))
    entry = result["results"][0]
    assert entry["status"] == "failed", result
    assert entry["exit_reason"] == "worker_budget"
    assert entry["budget_usage"]["total_tokens"] == 9
    assert entry["budget_usage"]["requests"] == 1
    assert log.exists()


def test_unverifiable_cost_is_rejected_before_child_execution(external_parent, monkeypatch):
    parent, log = external_parent
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: worker_config({"max_cost_usd": 1}))
    result = json.loads(delegate_tool.delegate_task(goal="Say done.", worker="external", parent_agent=parent))
    assert "max_cost_usd" in result["error"]
    assert "verifiable USD costs" in result["error"]
    assert not log.exists()
