"""Simulated record fixtures; these tests are not live Router qualification."""

import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "scripts/qualification/router_pilot_evidence.py"
SPEC = importlib.util.spec_from_file_location("router_pilot_evidence", SOURCE)
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)
MODEL = "openai/gpt-4.1-nano"


class DelegationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE messages (session_id, role, content, tool_calls, tool_call_id);
            CREATE TABLE async_delegations (delegation_id, state, parent_session_id, result_json);
        """)
        self.result = {"results": [{
            "status": "completed", "api_calls": 1, "model": MODEL,
            "summary": evidence.MARKER,
        }]}

    def call(self, arguments=None, session="parent", call_id="call"):
        calls = [{"id": call_id, "function": {
            "name": "delegate_task",
            "arguments": json.dumps(arguments or {"worker": "imagepilot", "tasks": [{"goal": "test"}]}),
        }}]
        self.db.execute("INSERT INTO messages VALUES (?, 'assistant', NULL, ?, NULL)", (session, json.dumps(calls)))

    def tool(self, payload, session="parent", call_id="call"):
        content = json.dumps(payload) if isinstance(payload, dict) else payload
        self.db.execute("INSERT INTO messages VALUES (?, 'tool', ?, NULL, ?)", (session, content, call_id))

    def collect(self):
        return evidence.collect_delegation_evidence(self.db, MODEL)

    def test_synchronous_named_result(self):
        self.call()
        self.tool(self.result)
        self.assertTrue(self.collect()["successful_worker_result"])

    def test_composite_call_id_matches_runtime_normalization(self):
        self.call(call_id="call|delegate_task")
        self.tool(self.result)
        self.assertTrue(self.collect()["successful_worker_result"])

    def test_multimodal_sqlite_content(self):
        self.call()
        self.tool("\x00json:" + json.dumps([{"type": "text", "text": json.dumps(self.result)}]))
        self.assertTrue(self.collect()["successful_worker_result"])

    def test_asynchronous_completion_is_correlated(self):
        self.call()
        self.tool({"status": "dispatched", "delegation_id": "batch"})
        self.db.execute("INSERT INTO async_delegations VALUES (?, ?, ?, ?)",
                        ("batch", "completed", "parent", json.dumps(self.result)))
        diagnostics = self.collect()
        self.assertEqual(diagnostics["async_completed_count"], 1)
        self.assertTrue(diagnostics["successful_worker_result"])

    def test_wrong_parent_cannot_supply_async_result(self):
        self.call()
        self.tool({"status": "dispatched", "delegation_id": "batch"})
        self.db.execute("INSERT INTO async_delegations VALUES (?, ?, ?, ?)",
                        ("batch", "completed", "other-parent", json.dumps(self.result)))
        self.assertFalse(self.collect()["successful_worker_result"])

    def test_incomplete_async_result_is_not_success(self):
        self.call()
        self.tool({"status": "dispatched", "delegation_id": "batch"})
        self.db.execute("INSERT INTO async_delegations VALUES (?, ?, ?, ?)",
                        ("batch", "running", "parent", json.dumps(self.result)))
        self.assertFalse(self.collect()["successful_worker_result"])

    def test_nested_worker_is_not_an_actual_worker_selection(self):
        self.call({"tasks": [{"goal": "test", "worker": "imagepilot"}]})
        self.tool(self.result)
        diagnostics = self.collect()
        self.assertFalse(diagnostics["registered_worker_requested"])
        self.assertFalse(diagnostics["successful_worker_result"])
        self.assertEqual(diagnostics["nested_worker_only_count"], 1)

    def test_wrong_call_and_session_are_rejected(self):
        self.call()
        self.tool(self.result, call_id="other-call")
        self.tool(self.result, session="other-parent")
        self.assertFalse(self.collect()["successful_worker_result"])

    def test_main_echo_is_not_proof(self):
        self.call()
        self.db.execute("INSERT INTO messages VALUES ('parent', 'assistant', ?, NULL, NULL)", (evidence.MARKER,))
        self.assertFalse(self.collect()["successful_worker_result"])

    def test_consumption_model_completion_and_errors_are_required(self):
        for mutation in [
            {"api_calls": 0}, {"api_calls": True}, {"api_calls": "1"},
            {"model": "wrong-model"}, {"status": "failed"}, {"error": "failed"},
        ]:
            with self.subTest(mutation=mutation):
                payload = {"results": [{**self.result["results"][0], **mutation}]}
                self.assertFalse(evidence.successful_worker_result(payload, MODEL))
        self.assertFalse(evidence.successful_worker_result({**self.result, "error": "failed"}, MODEL))

    def test_error_text_is_classified_but_never_retained(self):
        self.call()
        self.tool({"error": "Provider credential missing: sensitive-example"})
        diagnostics = self.collect()
        self.assertEqual(diagnostics["result_error_count"], 1)
        self.assertIn("credentials", diagnostics["failure_signals"])
        self.assertNotIn("sensitive-example", json.dumps(diagnostics))

    def test_invalid_payload_is_reported_not_accepted(self):
        self.call()
        self.tool("not JSON " + evidence.MARKER)
        diagnostics = self.collect()
        self.assertEqual(diagnostics["unparsed_tool_result_count"], 1)
        self.assertFalse(diagnostics["successful_worker_result"])


if __name__ == "__main__":
    unittest.main()
