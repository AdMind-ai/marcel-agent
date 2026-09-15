"""Deterministic contract-validator tests; no socket or external SDK required."""

import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from marcel_cli.marcel_router_validator import (
    FixtureTransport,
    Response,
    RouterValidator,
    UrlTransport,
)


def _completion(content="hello"):
    return {"id": "c", "object": "chat.completion", "created": 1, "model": "demo/chat",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def _metadata(capabilities):
    return {
        "capabilities": list(capabilities),
        "recommended_for": ["compatibility tests"],
        "cost_tier": "test",
        "speed_tier": "test",
        "quality_tier": "test",
        "context_window": 4096,
        "supports_streaming": "streaming" in capabilities,
        "supports_tool_calls": "tools" in capabilities,
        "supports_json_schema": "json_schema" in capabilities,
    }


class RouterValidatorTests(unittest.TestCase):
    def test_url_transport_normalizes_api_v1_and_sets_json_content_type(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.path, self.headers.get("Content-Type")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            transport = UrlTransport(f"http://127.0.0.1:{server.server_port}/api/v1", timeout=2)
            response = transport.request("POST", "/v1/translate", {"Accept": "application/json"}, {})
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertEqual(response.status, 200)
        self.assertEqual(seen, [("/api/v1/translate", "application/json")])

    def test_url_transport_refuses_redirect_before_cross_origin_authorization_leak(self):
        target_requests = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                target_requests.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args):
                pass

        target_server = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        target_thread = Thread(target=target_server.serve_forever, daemon=True)
        target_thread.start()

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{target_server.server_port}/stolen"
                )
                self.end_headers()

            def log_message(self, *_args):
                pass

        source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        source_thread = Thread(target=source.serve_forever, daemon=True)
        source_thread.start()
        try:
            transport = UrlTransport(f"http://127.0.0.1:{source.server_port}/api/v1", timeout=2)
            response = transport.request(
                "GET", "/v1/models",
                {"Accept": "application/json", "Authorization": "Bearer secret"},
            )
        finally:
            source.shutdown()
            source_thread.join()
            source.server_close()
            target_server.shutdown()
            target_thread.join()
            target_server.server_close()
        self.assertEqual(response.status, 302)
        self.assertEqual(target_requests, [])

    def test_url_transport_preserves_binary_and_enforces_response_limit(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/json" if self.path == "/too-large" else "video/mp4",
                )
                self.end_headers()
                payload = b"\x00\xff\x80"
                if self.path == "/large-video":
                    payload = payload * (22 * 1024)
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            transport = UrlTransport(f"http://127.0.0.1:{server.server_port}", timeout=2)
            response = transport.request("GET", "/video", {})
            self.assertEqual(response.body, b"\x00\xff\x80")
            streamed = transport.request("GET", "/large-video", {})
            self.assertEqual(len(streamed.body), 64 * 1024)
            self.assertTrue(streamed.truncated)
            limited = UrlTransport(
                f"http://127.0.0.1:{server.server_port}", timeout=2, max_response_bytes=2
            )
            with self.assertRaises(ValueError):
                limited.request("GET", "/too-large", {})
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_async_polling_is_bounded_on_a_job_that_never_finishes(self):
        class NeverFinishes:
            def __init__(self):
                self.polls = 0

            def request(self, method, path, headers, body=None):
                self.polls += 1
                return Response(
                    200,
                    {"content-type": "application/json"},
                    b'{"id":"job_1","status":"queued"}',
                )

        transport = NeverFinishes()
        validator = RouterValidator(transport, "token", poll_interval=0)
        with self.assertRaisesRegex(ValueError, "6 polls"):
            validator._poll_job("/v1/videos/job_1", terminal_statuses={"completed"})
        self.assertEqual(transport.polls, 6)

    def test_extended_semantics_reject_empty_or_meaningless_results(self):
        cases = [
            (
                "embeddings",
                [{"data": [], "usage": {"prompt_tokens": 1, "total_tokens": 1}}],
                "embeddings",
            ),
            (
                "moderation",
                [{"results": [{"flagged": "false"}]}],
                "moderation",
            ),
            (
                "reranking",
                [{"results": [{"index": 0, "relevance_score": "high"}]}],
                "reranking",
            ),
            (
                "translation",
                [{"translations": [{"text": "compatibility probe"}]}],
                "text translation",
            ),
            (
                "search_tools",
                [
                    {"object": "list", "data": [{"name": "brave_search"}]},
                    {
                        "provider": "brave", "query": "compatibility probe",
                        "data": [], "usage": {},
                    },
                ],
                "search and data tools",
            ),
        ]
        paths = {
            "embeddings": "/v1/embeddings",
            "moderation": "/v1/moderations",
            "reranking": "/v1/rerank",
            "translation": "/v1/translate",
        }
        for capability, bodies, check_name in cases:
            model = {
                "id": "demo/probe",
                "object": "model",
                "owned_by": "demo",
                "metadata": _metadata([capability]),
            }
            transport = FixtureTransport([
                {"method": "GET", "path": "/v1/tools"} if capability == "search_tools"
                else {"method": "POST", "path": paths[capability], "body": bodies[0]},
            ])
            if capability == "search_tools":
                transport.responses[0]["body"] = bodies[0]
                transport.responses.append({
                    "method": "POST", "path": "/v1/tools/search", "body": bodies[1],
                })
            validator = RouterValidator(transport, "token", poll_interval=0)
            validator.models = [model]
            validator._check_extended_capabilities()
            check = next(check for check in validator.report.checks if check.name == check_name)
            self.assertEqual(check.status, "fail", capability)

    def test_realtime_session_rejects_incomplete_or_malformed_credentials(self):
        valid = {
            "token": "one-use-token",
            "model": "demo/realtime",
            "websocket_url": "wss://example.test/realtime",
            "expires_at": "2030-01-01T00:00:00Z",
        }
        invalid_responses = [
            {**valid, "token": ""},
            {**valid, "websocket_url": "not-a-websocket-url"},
            {key: value for key, value in valid.items() if key != "expires_at"},
            {**valid, "expires_at": "2030-01-01"},
            {**valid, "model": "demo/other"},
        ]
        for body in invalid_responses:
            transport = FixtureTransport([{
                "method": "POST",
                "path": "/v1/realtime/sessions",
                "status": 201,
                "body": body,
            }])
            validator = RouterValidator(transport, "token", poll_interval=0)
            validator.models = [{
                "id": "demo/realtime",
                "object": "model",
                "owned_by": "demo",
                "metadata": _metadata(["realtime_voice"]),
            }]
            validator._check_extended_capabilities()
            check = next(
                check for check in validator.report.checks if check.name == "realtime voice"
            )
            self.assertEqual(check.status, "fail", body)

    def test_extended_capabilities_are_behaviorally_probed(self):
        """Every public extended endpoint gets a real request/response probe.

        The fixture is intentionally ordered like a live session.  This keeps
        the test deterministic while catching regressions such as an endpoint
        returning a schema-shaped object without a usable job lifecycle,
        binary content, or normalized tool result.
        """
        capabilities = [
            "chat", "streaming", "tools", "json_schema", "image_generation",
            "realtime_voice", "video_generation", "embeddings", "moderation",
            "reranking", "translation", "document_translation", "search_tools",
        ]
        model = {
            "id": "demo/multimodal",
            "object": "model",
            "created": 1,
            "owned_by": "demo",
            "metadata": _metadata(capabilities),
        }
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "echo", "arguments": "{}"},
        }
        video = {"id": "vid_1", "object": "video.job", "status": "completed"}
        document = {
            "id": "doc_1",
            "object": "document.translation",
            "status": "done",
        }
        responses = [
            {"method": "GET", "path": "/healthz", "body": {"status": "ok"}},
            {"method": "GET", "path": "/v1/models", "body": {"object": "list", "data": [model]}},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion()},
            {
                "method": "POST",
                "path": "/v1/chat/completions",
                "body": 'data: {"object":"chat.completion.chunk","choices":[]}\n\ndata: [DONE]\n\n',
            },
            {
                "method": "POST",
                "path": "/v1/chat/completions",
                "body": {
                    **_completion(),
                    "choices": [{"message": {"role": "assistant", "tool_calls": [tool_call]}}],
                },
            },
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion()},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion('{"ok": true}')},
            {
                "method": "POST",
                "path": "/v1/images/generations",
                "body": {"created": 1, "data": [{"url": "https://example.test/image.png"}]},
            },
            {
                "method": "POST",
                "path": "/v1/realtime/sessions",
                "status": 201,
                "body": {
                    "token": "one-use-token",
                    "model": model["id"],
                    "websocket_url": "wss://example.test/realtime",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            },
            {"method": "POST", "path": "/v1/videos", "status": 202, "body": video},
            {"method": "GET", "path": "/v1/videos/vid_1", "body": video},
            {
                "method": "GET",
                "path": "/v1/videos/vid_1/content",
                "headers": {"Content-Type": "video/mp4"},
                "body": "video-bytes",
            },
            {
                "method": "DELETE",
                "path": "/v1/videos/vid_1",
                "status": 204,
                "body": "",
            },
            {
                "method": "POST",
                "path": "/v1/embeddings",
                "body": {
                    "object": "list",
                    "model": model["id"],
                    "data": [{"object": "embedding", "embedding": [0.1], "index": 0}],
                    "usage": {"prompt_tokens": 2, "total_tokens": 2},
                },
            },
            {
                "method": "POST",
                "path": "/v1/moderations",
                "body": {
                    "id": "mod_1", "model": model["id"],
                    "results": [{
                        "flagged": False,
                        "categories": {"violence": False},
                        "category_scores": {"violence": 0.0},
                    }],
                },
            },
            {
                "method": "POST",
                "path": "/v1/rerank",
                "body": {"results": [{"index": 0, "relevance_score": 0.9}]},
            },
            {
                "method": "POST",
                "path": "/v1/translate",
                "body": {"translations": [{"text": "sonda", "detected_source_language": "en"}]},
            },
            {"method": "POST", "path": "/v1/documents/translations", "status": 202, "body": document},
            {"method": "GET", "path": "/v1/documents/translations/doc_1", "body": document},
            {
                "method": "GET",
                "path": "/v1/documents/translations/doc_1/content",
                "headers": {"Content-Type": "application/pdf"},
                "body": "translated-document-bytes",
            },
            {
                "method": "GET",
                "path": "/v1/tools",
                "body": {"object": "list", "data": [{"name": "brave_search"}]},
            },
            {
                "method": "POST",
                "path": "/v1/tools/search",
                "body": {
                    "provider": "brave", "query": "compatibility probe",
                    "data": [{"title": "Probe result", "url": "https://example.test"}],
                    "usage": {},
                },
            },
            {
                "method": "GET",
                "path": "/v1/models",
                "status": 401,
                "body": {"error": {"message": "missing", "type": "authentication_error"}},
            },
            {
                "method": "POST",
                "path": "/v1/chat/completions",
                "status": 404,
                "body": {"error": {"message": "unknown", "type": "invalid_request_error"}},
            },
        ]
        transport = FixtureTransport(responses)
        report = RouterValidator(transport, "test-token", poll_interval=0).run()

        self.assertTrue(report.ok)
        self.assertFalse(transport.responses)
        self.assertEqual(
            {check.name for check in report.checks if check.status == "fail"},
            set(),
        )
        document_request = next(
            request for request in transport.requests
            if request[1] == "/v1/documents/translations"
        )
        self.assertIsInstance(document_request[3], bytes)
        self.assertTrue(document_request[3].startswith(b"--marcel-router-validator-boundary"))
        self.assertTrue(
            document_request[2]["Content-Type"].startswith("multipart/form-data; boundary=")
        )
        pdf = document_request[3].split(
            b"Content-Type: application/pdf\r\n\r\n", 1
        )[1].split(b"\r\n--marcel-router-validator-boundary", 1)[0]
        self.assertTrue(pdf.startswith(b"%PDF-1.4\n"))
        self.assertIn(b"\nxref\n", pdf)
        self.assertIn(b"\n%%EOF\n", pdf)
        startxref = int(pdf.rsplit(b"startxref\n", 1)[1].splitlines()[0])
        self.assertEqual(pdf[startxref:startxref + 4], b"xref")
        self.assertFalse(
            any(request[1] == "/v1/realtime/connect" for request in transport.requests)
        )

    def test_complete_fixture_passes_and_uses_no_network(self):
        model = {
            "id": "demo/chat", "object": "model", "created": 1, "owned_by": "demo",
            "metadata": _metadata(["chat", "streaming", "tools", "json_schema"]),
        }
        tool_call = {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}
        responses = [
            {"method": "GET", "path": "/healthz", "body": {"status": "ok", "version": "1.0.0"}},
            {"method": "GET", "path": "/v1/models", "body": {"object": "list", "data": [model]}},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion()},
            {"method": "POST", "path": "/v1/chat/completions", "body": 'data: {"object":"chat.completion.chunk","choices":[]}\n\ndata: [DONE]\n\n'},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion()},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion()},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion('{"ok": true}')},
            {"method": "GET", "path": "/v1/models", "status": 401, "body": {"error": {"message": "missing", "type": "authentication_error"}}},
            {"method": "POST", "path": "/v1/chat/completions", "status": 404, "body": {"error": {"message": "unknown", "type": "invalid_request_error"}}},
        ]
        # Substitute the first tool response with an actual tool-call completion.
        responses[4]["body"] = _completion()
        responses[4]["body"]["choices"][0]["message"] = {"role": "assistant", "tool_calls": [tool_call]}
        transport = FixtureTransport(responses)
        report = RouterValidator(transport, "test-token").run()
        self.assertTrue(report.ok)
        self.assertFalse(transport.responses)
        self.assertNotIn("Authorization", transport.requests[-2][2])

    def test_catalog_rejects_legacy_validator_only_metadata(self):
        transport = FixtureTransport([
            {"method": "GET", "path": "/healthz", "body": {"status": "ok"}},
            {
                "method": "GET",
                "path": "/v1/models",
                "body": {
                    "object": "list",
                    "data": [{
                        "id": "demo/chat",
                        "object": "model",
                        "owned_by": "demo",
                        "marcel": {"capabilities": {"chat": True}},
                    }],
                },
            },
            {
                "method": "GET",
                "path": "/v1/models",
                "status": 401,
                "body": {"error": {"message": "missing", "type": "authentication_error"}},
            },
        ])
        report = RouterValidator(transport, "token").run()
        self.assertFalse(report.ok)
        self.assertEqual(
            next(check for check in report.checks if check.name == "model catalog").status,
            "fail",
        )

    def test_metadata_support_flags_select_chat_feature_probes(self):
        metadata = _metadata(["chat"])
        metadata.update({
            "supports_streaming": True,
            "supports_tool_calls": True,
            "supports_json_schema": True,
        })
        model = {
            "id": "demo/chat",
            "object": "model",
            "owned_by": "demo",
            "metadata": metadata,
        }
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "echo", "arguments": "{}"},
        }
        responses = [
            {"method": "GET", "path": "/healthz", "body": {"status": "ok"}},
            {"method": "GET", "path": "/v1/models", "body": {"object": "list", "data": [model]}},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion()},
            {"method": "POST", "path": "/v1/chat/completions",
             "body": 'data: {"object":"chat.completion.chunk","choices":[]}\n\ndata: [DONE]\n\n'},
            {"method": "POST", "path": "/v1/chat/completions",
             "body": {**_completion(),
                      "choices": [{"message": {"role": "assistant", "tool_calls": [tool_call]}}]}},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion()},
            {"method": "POST", "path": "/v1/chat/completions", "body": _completion('{"ok": true}')},
            {"method": "GET", "path": "/v1/models", "status": 401,
             "body": {"error": {"message": "missing", "type": "authentication_error"}}},
            {"method": "POST", "path": "/v1/chat/completions", "status": 404,
             "body": {"error": {"message": "unknown", "type": "invalid_request_error"}}},
        ]
        transport = FixtureTransport(responses)
        report = RouterValidator(transport, "token", poll_interval=0).run()
        self.assertTrue(report.ok)
        self.assertEqual(
            {check.name for check in report.checks if check.status == "pass"},
            {
                "health", "model catalog", "non-stream chat", "SSE streaming",
                "tool calling", "structured JSON output", "authentication error envelope",
                "request error envelope",
            },
        )

    def test_invalid_sse_is_reported_without_raising(self):
        transport = FixtureTransport([
            {"body": {"status": "ok", "version": "1"}},
            {"body": {"object": "list", "data": [{
                "id": "x/y", "object": "model", "owned_by": "x",
                "metadata": _metadata(["chat", "streaming"]),
            }]}},
            {"body": _completion()},
            {"body": "data: nope\n\n"},
            {"status": 401, "body": {"error": {"message": "no", "type": "authentication_error"}}},
            {"status": 400, "body": {"error": {"message": "bad", "type": "invalid_request_error"}}},
        ])
        report = RouterValidator(transport, "token").run()
        self.assertFalse(report.ok)
        self.assertEqual(next(c.status for c in report.checks if c.name == "SSE streaming"), "fail")