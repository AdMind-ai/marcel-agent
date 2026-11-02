"""Request-size failures and truncated summaries must not erase a conversation."""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agent.context_compressor import ContextCompressor
from agent.context_recovery import recovery_notice, save_recovery_snapshot
from agent.payload_diagnostics import compact_utf8_input, payload_metrics, wire_metrics
from gateway.run_turn import GatewayTurnMixin


def test_payload_metrics_do_not_log_content_or_keys(caplog):
    from agent.payload_diagnostics import log_summary_request
    rows = [{"role": "user", "content": "private-transcript-fixture"},
            {"role": "tool", "content": "worker-result-fixture"}]
    with caplog.at_level("INFO"):
        log_summary_request(rows, {"provider": "custom", "model": "test"}, client_request_id="fixture-id")
    assert "private-transcript-fixture" not in caplog.text
    assert "worker-result-fixture" not in caplog.text
    assert '"message_count": 2' in caplog.text
    assert '"timezone": "UTC"' in caplog.text
    measured = wire_metrics({"messages": rows, "extra_headers": {"Authorization": "private-key"}, "model": "test"})
    assert "private-key" not in json.dumps(measured)
    assert measured["serialized_body_bytes"] > measured["messages_bytes"]


def test_utf8_recovery_input_is_bounded_and_samples_head_middle_tail():
    text = "START" + ("à漢" * 40000) + "END"
    compact = compact_utf8_input(text, 24000)
    assert len(compact.encode()) <= 24000
    assert compact.startswith("START") and compact.endswith("END")
    assert compact.count("archived content omitted") == 7


def _response(text, reason):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=reason)])


def _compressor():
    with patch("agent.context_compressor.get_model_context_length", return_value=128000):
        return ContextCompressor(model="test", quiet_mode=True, protect_first_n=1, protect_last_n=1)


def test_truncated_summary_has_one_smaller_retry_then_complete_checkpoint():
    compressor = _compressor()
    messages = [{"role": "user", "content": "Puoi mandarmi un audio?"}]
    messages += [{"role": "tool", "content": f"worker-{i} " + "risultato " * 6000} for i in range(3)]
    good = "## Active Task\nRispondere al vocale.\n## User Prompts\n- Puoi mandarmi un audio?\n## Completed Actions\nTre risultati consegnati."
    with patch("agent.context_compressor.call_llm", side_effect=[
        _response("DO_NOT_STORE_PARTIAL", "length"), _response(good, "stop"),
    ]) as call:
        result = compressor._generate_summary(messages)
    assert result and "DO_NOT_STORE_PARTIAL" not in result
    assert call.call_count == 2
    first, retry = (c.kwargs["messages"][0]["content"] for c in call.call_args_list)
    assert len(retry.encode()) < len(first.encode())
    assert "Target ~768 tokens" in retry
    assert call.call_args_list[0].kwargs["extra_headers"]["X-Client-Request-Id"] != call.call_args_list[1].kwargs["extra_headers"]["X-Client-Request-Id"]


def test_two_truncated_summaries_never_replace_previous_checkpoint():
    compressor = _compressor()
    compressor._previous_summary = "existing checkpoint"
    with patch("agent.context_compressor.call_llm", return_value=_response("INCOMPLETE", "length")) as call:
        assert compressor._generate_summary([{"role": "user", "content": "continua"}]) is None
        assert compressor._generate_summary([{"role": "user", "content": "continua"}]) is None
    assert call.call_count == 2
    assert compressor._previous_summary == "existing checkpoint"
    assert compressor._last_summary_truncated_failure


def test_private_snapshot_preserves_history_and_pending_request(tmp_path, monkeypatch):
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    messages = [{"role": "user", "content": "richiesta precedente"}]
    pending = {"role": "user", "content": "puoi mandarmi un audio?"}
    name = save_recovery_snapshot("session-fixture", messages, pending_request=pending)
    path = tmp_path / "recovery" / "context" / name
    stored = json.loads(path.read_text())
    assert stored["messages"] == messages and stored["pending_request"] == pending
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("flag", ["payload_too_large", "compression_exhausted"])
def test_gateway_preserves_session_and_binding_instead_of_auto_reset(tmp_path, monkeypatch, flag):
    monkeypatch.setenv("MARCEL_HOME", str(tmp_path))
    runner = SimpleNamespace(
        async_session_store=SimpleNamespace(reset_session=AsyncMock()),
        _evict_cached_agent=Mock(), _clear_conversation_scope=Mock(), _sync_telegram_topic_binding=Mock(),
    )
    entry = SimpleNamespace(session_id="session-fixture")
    pending = {"role": "user", "content": "puoi mandarmi un audio?"}
    result = {flag: True, "messages": [{"role": "user", "content": "ciao"}], "failed": True}
    response, kept = asyncio.run(GatewayTurnMixin._hmwa_compression_exhaustion_reset(
        runner, result, "old response", entry, "session-key-fixture", None, pending_request=pending,
    ))
    assert kept is entry
    assert "non viene azzerata" in response
    assert "auto-reset" not in response
    assert result["session_preserved"]
    assert (tmp_path / "recovery" / "context" / result["recovery_snapshot"]).is_file()
    runner.async_session_store.reset_session.assert_not_called()
    runner._evict_cached_agent.assert_not_called()
    runner._sync_telegram_topic_binding.assert_not_called()


def test_http_413_is_not_classified_as_context_window_overflow():
    runner = SimpleNamespace(_CONTEXT_OVERFLOW_ERROR_PHRASES=GatewayTurnMixin._CONTEXT_OVERFLOW_ERROR_PHRASES)
    result = {"failed": True, "payload_too_large": True, "error": "HTTP 413 payload too large"}
    _, _, context_failure = GatewayTurnMixin._hmwa_classify_turn_failure(runner, result, [{}] * 100, SimpleNamespace(session_id="test"))
    assert not context_failure
    result = {"failed": True, "error": "HTTP 400 invalid request"}
    assert not GatewayTurnMixin._hmwa_classify_turn_failure(runner, result, [{}] * 100, SimpleNamespace(session_id="test"))[2]


def test_localized_notice_does_not_claim_413_proves_context_exhaustion():
    notice = recovery_notice([{"role": "user", "content": "ciao, puoi aiutarmi?"}])
    assert "HTTP" in notice and "413" in notice
    assert "Non è una prova" in notice and "non viene azzerata" in notice
    metrics = payload_metrics([{"role": "user", "content": "ciao"}], [{"type": "function"}])
    assert metrics["tools_count"] == 1 and metrics["inline_media_bytes"] == 0
