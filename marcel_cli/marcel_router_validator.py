"""Offline-capable compatibility checks for the Marcel Router v1 contract.

Run ``marcel-router-validate --fixture router.json`` for a deterministic
fixture run, or set the named environment variable and pass ``--base-url`` for
an actual router.  Fixture files are JSON and contain an ordered ``responses``
list; each item has ``method``, ``path``, ``status``, optional ``headers``, and
``body`` (an object or string).  They deliberately have no credential field.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    truncated: bool = False


class Transport(Protocol):
    def request(self, method: str, path: str, headers: dict[str, str],
                body: dict[str, Any] | bytes | None = None) -> Response: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never follow redirects with bearer credentials attached.

    API endpoints should return their result directly.  Refusing redirects is
    safer than trying to reason about every redirect variant and guarantees an
    accidental cross-origin response cannot receive the Marcel token.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


class UrlTransport:
    """Small stdlib transport, intentionally avoiding an SDK-specific client."""

    def __init__(
        self, base_url: str, timeout: float, max_response_bytes: int = 8 * 1024 * 1024,
        max_binary_prefix_bytes: int = 64 * 1024,
    ) -> None:
        parsed = urlsplit(base_url.strip())
        path = parsed.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3].rstrip("/")
        self.base_url = urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.max_binary_prefix_bytes = max_binary_prefix_bytes
        self._opener = urllib.request.build_opener(_NoRedirectHandler)

    def request(self, method: str, path: str, headers: dict[str, str],
                body: dict[str, Any] | bytes | None = None) -> Response:
        if isinstance(body, bytes):
            data = body
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
        else:
            data = None
        request_headers = dict(headers)
        if body is not None and not any(k.lower() == "content-type" for k in request_headers):
            request_headers["Content-Type"] = (
                "application/json" if isinstance(body, dict) else "application/octet-stream")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers=request_headers
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as result:
                response_headers = {k.lower(): v for k, v in result.headers.items()}
                body, truncated = self._read_response(result, response_headers)
                return Response(result.status, response_headers, body, truncated)
        except urllib.error.HTTPError as error:
            response_headers = {k.lower(): v for k, v in error.headers.items()}
            body, truncated = self._read_response(error, response_headers)
            return Response(error.code, response_headers, body, truncated)

    def _read_response(self, response, headers: dict[str, str]) -> tuple[bytes, bool]:
        content_type = headers.get("content-type", "").lower()
        media_type = content_type.split(";", 1)[0].strip()
        is_binary_media = content_type.startswith("video/") or media_type in {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        limit = self.max_binary_prefix_bytes if is_binary_media else self.max_response_bytes
        body = response.read(limit + 1)
        if is_binary_media:
            return body[:limit], len(body) > limit
        if len(body) > limit:
            raise ValueError(
                f"response exceeded {self.max_response_bytes} byte limit")
        return body, False


class FixtureTransport:
    """Ordered fake transport for CLI fixtures and unit tests."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, str], dict[str, Any] | bytes | None]] = []

    def request(self, method: str, path: str, headers: dict[str, str],
                body: dict[str, Any] | bytes | None = None) -> Response:
        if not self.responses:
            raise AssertionError(f"fixture has no response for {method} {path}")
        item = self.responses.pop(0)
        if item.get("method", method).upper() != method.upper() or item.get("path", path) != path:
            raise AssertionError(f"fixture expected {item.get('method')} {item.get('path')}, got {method} {path}")
        request_headers = dict(headers)
        if body is not None and not any(k.lower() == "content-type" for k in request_headers):
            request_headers["Content-Type"] = (
                "application/json" if isinstance(body, dict) else "application/octet-stream")
        self.requests.append((method, path, request_headers, body))
        content = item.get("body", "")
        if isinstance(content, bytes):
            body_bytes = content
        elif isinstance(content, str):
            body_bytes = content.encode("utf-8")
        else:
            body_bytes = json.dumps(content).encode("utf-8")
        response_headers = {str(k).lower(): str(v)
                            for k, v in item.get("headers", {}).items()}
        if isinstance(content, (dict, list)) and "content-type" not in response_headers:
            response_headers["content-type"] = "application/json"
        return Response(int(item.get("status", 200)), response_headers, body_bytes)


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name, status, detail))

    @property
    def ok(self) -> bool:
        return not any(check.status == "fail" for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        counts = {state: sum(c.status == state for c in self.checks)
                  for state in ("pass", "fail", "skip")}
        return {"ok": self.ok, "summary": counts,
                "checks": [check.__dict__ for check in self.checks]}


class RouterValidator:
    """Validate the contract portions clients rely on, not implementation details."""

    def __init__(
        self, transport: Transport, token: str | None, *,
        max_polls: int = 6, poll_interval: float = 1.0,
    ) -> None:
        self.transport, self.token, self.report = transport, token, Report()
        self.models: list[dict[str, Any]] = []
        self.max_polls = max(1, max_polls)
        self.poll_interval = max(0.0, poll_interval)

    def _headers(self, authenticated: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _json(self, response: Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "").lower()
        if not (content_type.startswith("application/json")
                or content_type.endswith("+json")):
            raise ValueError("JSON response must use an application/json content type")
        try:
            value = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            detail = getattr(exc, "msg", str(exc))
            raise ValueError(f"invalid JSON: {detail}") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON response must be an object")
        return value

    @staticmethod
    def _is_rfc3339(value: Any) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None

    def _poll_job(self, path: str, *, terminal_statuses: set[str]) -> dict[str, Any]:
        """Poll an asynchronous job with a hard request and time bound."""
        started = time.monotonic()
        for attempt in range(self.max_polls):
            response = self.transport.request("GET", path, self._headers())
            value = self._json(response)
            if response.status != 200:
                raise ValueError(f"job poll returned HTTP {response.status}")
            status = value.get("status")
            if status in terminal_statuses:
                if status in {"failed", "error", "cancelled", "canceled"}:
                    raise ValueError(f"job ended in {status} state")
                return value
            if attempt + 1 < self.max_polls and self.poll_interval:
                time.sleep(self.poll_interval)
            if time.monotonic() - started > self.max_polls * max(self.poll_interval, 0.01):
                break
        raise ValueError(f"job did not reach a terminal state after {self.max_polls} polls")

    @staticmethod
    def _multipart_document() -> tuple[bytes, str]:
        """Build a contract-correct multipart body with a valid one-page PDF."""
        boundary = "marcel-router-validator-boundary"
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
            b"/Resources << >> /Contents 4 0 R >>",
            b"<< /Length 0 >>\nstream\nendstream",
        ]
        pdf_parts = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(sum(map(len, pdf_parts)))
            pdf_parts.extend([f"{index} 0 obj\n".encode("ascii"), obj, b"\nendobj\n"])
        xref_offset = sum(map(len, pdf_parts))
        pdf_parts.extend([
            f"xref\n0 {len(objects) + 1}\n".encode("ascii"),
            b"0000000000 65535 f \n",
        ])
        pdf_parts.extend(
            f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]
        )
        pdf_parts.append(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        file_data = b"".join(pdf_parts)
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="probe.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("ascii") + file_data + (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="target_lang"\r\n\r\n'
            "it\r\n"
            f"--{boundary}--\r\n"
        ).encode("ascii")
        return body, f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _error(value: dict[str, Any]) -> bool:
        error = value.get("error")
        return isinstance(error, dict) and isinstance(error.get("message"), str) and isinstance(error.get("type"), str)

    def _check(self, name: str, action) -> Any:
        try:
            result = action()
            self.report.add(name, "pass")
            return result
        except Exception as exc:  # A report should include every independently runnable check.
            self.report.add(name, "fail", str(exc))
            return None

    def _model(self, capability: str = "chat") -> dict[str, Any] | None:
        metadata_flags = {
            "streaming": "supports_streaming",
            "tools": "supports_tool_calls",
            "json_schema": "supports_json_schema",
        }
        for model in self.models:
            metadata = model.get("metadata", {})
            capabilities = metadata.get("capabilities", []) if isinstance(metadata, dict) else []
            if (metadata_flags.get(capability) and
                    isinstance(metadata, dict) and metadata.get(metadata_flags[capability]) is True):
                return model
            if capability not in metadata_flags and capability in capabilities:
                return model
        return None

    def _extended_model(self, *capabilities: str) -> dict[str, Any] | None:
        """Return a model advertising one of the extended v1 capabilities.

        Extended operations are deliberately probed only when the catalogue says
        they are available.  This keeps the validator useful for small
        OpenAI-compatible deployments while making a claimed capability a
        behavioral, rather than schema-only, contract.
        """
        for capability in capabilities:
            model = self._model(capability)
            if model:
                return model
        return None

    def _check_extended_capabilities(self) -> None:
        """Exercise each extended endpoint advertised by the model catalogue."""
        headers = self._headers()

        image_model = self._extended_model("image_generation", "images")
        if image_model:
            def image_generation() -> None:
                response = self.transport.request(
                    "POST", "/v1/images/generations", headers,
                    {"model": image_model["id"], "prompt": "compatibility probe"},
                )
                value = self._json(response)
                data = value.get("data")
                if response.status != 200 or not isinstance(data, list) or not data:
                    raise ValueError("expected generated image data")
                if not all(isinstance(item, dict) and (item.get("url") or item.get("b64_json"))
                           for item in data):
                    raise ValueError("generated images require url or b64_json")
            self._check("image generation", image_generation)
        else:
            self.report.add("image generation", "skip", "no catalog model advertises image generation")

        realtime_model = self._extended_model("realtime_voice", "realtime")
        if realtime_model:
            def realtime() -> None:
                response = self.transport.request(
                    "POST", "/v1/realtime/sessions", headers,
                    {"model": realtime_model["id"], "recording_consent": True,
                     "audio_processing_consent": True},
                )
                value = self._json(response)
                if (response.status != 201
                        or not isinstance(value.get("token"), str)
                        or not value["token"].strip()
                        or not isinstance(value.get("websocket_url"), str)
                        or not value["websocket_url"].strip()):
                    raise ValueError("expected non-empty realtime session credentials")
                websocket = urlsplit(value["websocket_url"])
                if websocket.scheme not in {"ws", "wss"} or not websocket.netloc:
                    raise ValueError("realtime websocket_url must be a ws/wss URL")
                if not self._is_rfc3339(value.get("expires_at")):
                    raise ValueError("realtime expires_at must be RFC3339")
                if value.get("model") != realtime_model["id"]:
                    raise ValueError("realtime response must echo the requested model")
            self._check("realtime voice", realtime)
            self.report.add(
                "realtime WebSocket exchange", "skip",
                "live WebSocket transport is required for handshake and event validation",
            )
        else:
            self.report.add("realtime voice", "skip", "no catalog model advertises realtime voice")

        video_model = self._extended_model("video_generation", "video")
        if video_model:
            def video_generation() -> None:
                response = self.transport.request(
                    "POST", "/v1/videos", headers,
                    {"model": video_model["id"], "prompt": "compatibility probe"},
                )
                value = self._json(response)
                video_id = value.get("id")
                if (response.status != 202 or not isinstance(video_id, str)
                        or value.get("object") != "video.job"):
                    raise ValueError("expected accepted video job")
                status_value = self._poll_job(
                    f"/v1/videos/{video_id}",
                    terminal_statuses={"completed", "succeeded", "failed", "error",
                                       "cancelled", "canceled"},
                )
                if status_value.get("id") != video_id:
                    raise ValueError("expected video status")
                content = self.transport.request(
                    "GET", f"/v1/videos/{video_id}/content", headers,
                )
                if (content.status != 200 or not content.body
                        or not content.headers.get("content-type", "").lower().startswith("video/")):
                    raise ValueError("expected completed video content")
                deleted = self.transport.request(
                    "DELETE", f"/v1/videos/{video_id}", headers,
                )
                if deleted.status != 204 or deleted.body:
                    raise ValueError("expected video deletion response")
            self._check("video generation lifecycle", video_generation)
        else:
            self.report.add("video generation lifecycle", "skip",
                            "no catalog model advertises video generation")

        embedding_model = self._extended_model("embeddings", "embedding")
        if embedding_model:
            def embeddings() -> None:
                response = self.transport.request(
                    "POST", "/v1/embeddings", headers,
                    {"model": embedding_model["id"], "input": "compatibility probe",
                     "encoding_format": "float"},
                )
                value = self._json(response)
                data = value.get("data")
                usage = value.get("usage")
                if (response.status != 200 or not isinstance(data, list)
                        or len(data) != 1 or not isinstance(usage, dict)):
                    raise ValueError("expected one embedding and usage")
                item = data[0]
                embedding = item.get("embedding") if isinstance(item, dict) else None
                if (not isinstance(item, dict) or item.get("object") != "embedding"
                        or item.get("index") != 0
                        or not (isinstance(embedding, list) and embedding
                                and all(isinstance(number, (int, float))
                                        and not isinstance(number, bool)
                                        and math.isfinite(number) for number in embedding))):
                    raise ValueError("embedding data is empty or meaningless")
                if (not isinstance(usage.get("prompt_tokens"), int)
                        or usage["prompt_tokens"] < 0
                        or not isinstance(usage.get("total_tokens"), int)
                        or usage["total_tokens"] < usage["prompt_tokens"]):
                    raise ValueError("embedding usage is invalid")
            self._check("embeddings", embeddings)
        else:
            self.report.add("embeddings", "skip", "no catalog model advertises embeddings")

        moderation_model = self._extended_model("moderation", "moderations")
        if moderation_model:
            def moderation() -> None:
                response = self.transport.request(
                    "POST", "/v1/moderations", headers,
                    {"model": moderation_model["id"], "input": "compatibility probe"},
                )
                value = self._json(response)
                results = value.get("results")
                if (response.status != 200 or not isinstance(results, list)
                        or not results):
                    raise ValueError("expected moderation results")
                for result in results:
                    if (not isinstance(result, dict)
                            or not isinstance(result.get("flagged"), bool)
                            or not isinstance(result.get("categories"), dict)
                            or not result["categories"]
                            or not isinstance(result.get("category_scores"), dict)
                            or not result["category_scores"]):
                        raise ValueError("moderation result is empty or meaningless")
            self._check("moderation", moderation)
        else:
            self.report.add("moderation", "skip", "no catalog model advertises moderation")

        rerank_model = self._extended_model("reranking", "rerank")
        if rerank_model:
            def rerank() -> None:
                response = self.transport.request(
                    "POST", "/v1/rerank", headers,
                    {"model": rerank_model["id"], "query": "compatibility probe",
                     "documents": ["compatibility result"]},
                )
                value = self._json(response)
                results = value.get("results")
                if (response.status != 200 or not isinstance(results, list)
                        or len(results) != 1):
                    raise ValueError("expected one reranking result")
                result = results[0]
                score = result.get("relevance_score") if isinstance(result, dict) else None
                if (not isinstance(result, dict) or result.get("index") != 0
                        or not isinstance(score, (int, float)) or isinstance(score, bool)
                        or not math.isfinite(score)):
                    raise ValueError("reranking result is empty or meaningless")
            self._check("reranking", rerank)
        else:
            self.report.add("reranking", "skip", "no catalog model advertises reranking")

        translation_model = self._extended_model("translation")
        if translation_model:
            def translation() -> None:
                response = self.transport.request(
                    "POST", "/v1/translate", headers,
                    {"text": "compatibility probe", "target_lang": "it"},
                )
                value = self._json(response)
                translations = value.get("translations")
                if (response.status != 200 or not isinstance(translations, list)
                        or not translations):
                    raise ValueError("translation response has no translated text")
                for item in translations:
                    if (not isinstance(item, dict) or not isinstance(item.get("text"), str)
                            or not item["text"].strip()
                            or item["text"].strip().lower() == "compatibility probe"):
                        raise ValueError("translation response is empty or meaningless")
            self._check("text translation", translation)
        else:
            self.report.add("text translation", "skip", "no catalog model advertises translation")

        document_model = self._extended_model("document_translation", "document_translations")
        if document_model:
            def document_translation() -> None:
                # The upload is multipart, not JSON.  Keep the content type
                # explicit even for transports that do not infer it.
                multipart_body, content_type = self._multipart_document()
                response = self.transport.request(
                    "POST", "/v1/documents/translations",
                    {**headers, "Content-Type": content_type},
                    multipart_body,
                )
                value = self._json(response)
                document_id = value.get("id")
                if (response.status != 202 or not isinstance(document_id, str)
                        or value.get("object") != "document.translation"):
                    raise ValueError("expected accepted document translation")
                status_value = self._poll_job(
                    f"/v1/documents/translations/{document_id}",
                    terminal_statuses={"done", "error", "expired"},
                )
                if status_value.get("id") != document_id:
                    raise ValueError("expected document translation status")
                content = self.transport.request(
                    "GET", f"/v1/documents/translations/{document_id}/content", headers,
                )
                if (content.status != 200 or not content.body
                        or not content.headers.get("content-type", "").lower().startswith("application/")):
                    raise ValueError("expected translated document content")
            self._check("document translation lifecycle", document_translation)
        else:
            self.report.add("document translation lifecycle", "skip",
                            "no catalog model advertises document translation")

        tools_model = self._extended_model("search_tools", "tools_search", "search")
        if tools_model:
            def search_tools() -> None:
                catalog = self.transport.request("GET", "/v1/tools", headers)
                catalog_value = self._json(catalog)
                if (catalog.status != 200 or catalog_value.get("object") != "list"
                        or not isinstance(catalog_value.get("data"), list)
                        or not catalog_value["data"]
                        or not all(isinstance(item, dict) and isinstance(item.get("name"), str)
                                   and item["name"].strip() for item in catalog_value["data"])):
                    raise ValueError("expected tool catalog")
                response = self.transport.request(
                    "POST", "/v1/tools/search", headers,
                    {"provider": "brave", "query": "compatibility probe"},
                )
                value = self._json(response)
                if (response.status != 200 or value.get("provider") != "brave"
                        or value.get("query") != "compatibility probe"
                        or not isinstance(value.get("data"), list)
                        or not value["data"] or not isinstance(value.get("usage"), dict)
                        or not all(
                            (isinstance(item, dict) and any(
                                isinstance(item.get(key), str) and item[key].strip()
                                for key in ("title", "url", "snippet", "content")
                            )) or (isinstance(item, str) and item.strip())
                            for item in value["data"]
                        )):
                    raise ValueError("search tool response is empty or meaningless")
            self._check("search and data tools", search_tools)
        else:
            self.report.add("search and data tools", "skip",
                            "no catalog model advertises search/data tools")

    def _completion(self, model: dict[str, Any], **extra: Any) -> Response:
        payload = {"model": model["id"], "messages": [{"role": "user", "content": "compatibility probe"}]}
        payload.update(extra)
        return self.transport.request("POST", "/v1/chat/completions", self._headers(), payload)

    def run(self) -> Report:
        def health() -> None:
            response = self.transport.request("GET", "/healthz", self._headers(False))
            value = self._json(response)
            if response.status != 200 or value.get("status") != "ok":
                raise ValueError("expected 200 health object with status=ok")
            if "version" in value and not isinstance(value["version"], str):
                raise ValueError("health version must be a string when present")
        self._check("health", health)

        def catalog() -> list[dict[str, Any]]:
            response = self.transport.request("GET", "/v1/models", self._headers())
            value = self._json(response)
            data = value.get("data")
            if response.status != 200 or value.get("object") != "list" or not isinstance(data, list) or not data:
                raise ValueError("expected non-empty OpenAI model list")
            for model in data:
                if (not isinstance(model, dict)
                        or not isinstance(model.get("id"), str)
                        or "/" not in model["id"]
                        or model.get("object") != "model"
                        or not isinstance(model.get("owned_by"), str)):
                    raise ValueError("models require namespaced IDs and model ownership")
                metadata = model.get("metadata")
                required_metadata = {
                    "capabilities", "recommended_for", "cost_tier", "speed_tier",
                    "quality_tier", "context_window", "supports_streaming",
                    "supports_tool_calls", "supports_json_schema",
                }
                if not isinstance(metadata, dict) or not required_metadata <= metadata.keys():
                    raise ValueError("models require canonical metadata")
                if (not isinstance(metadata["capabilities"], list)
                        or not metadata["capabilities"]
                        or not all(isinstance(capability, str) and capability.strip()
                                   for capability in metadata["capabilities"])
                        or not isinstance(metadata["recommended_for"], list)
                        or not all(isinstance(item, str) for item in metadata["recommended_for"])
                        or not isinstance(metadata["context_window"], int)
                        or metadata["context_window"] <= 0
                        or not all(isinstance(metadata[key], str) and metadata[key].strip()
                                   for key in ("cost_tier", "speed_tier", "quality_tier"))
                        or not all(isinstance(metadata[key], bool) for key in (
                            "supports_streaming", "supports_tool_calls", "supports_json_schema"))):
                    raise ValueError("model metadata has invalid canonical field types")
            return data
        self.models = self._check("model catalog", catalog) or []

        chat_model = self._model()
        if not chat_model:
            self.report.add("non-stream chat", "skip", "no catalog model advertises chat")
            self.report.add("SSE streaming", "skip", "no catalog model advertises chat")
            self.report.add("tool calling", "skip", "no catalog model advertises chat")
            self.report.add("structured JSON output", "skip", "no catalog model advertises chat")
        else:
            def nonstream() -> None:
                response = self._completion(chat_model, stream=False)
                value = self._json(response)
                usage = value.get("usage", {})
                if response.status != 200 or value.get("object") != "chat.completion" or not isinstance(value.get("choices"), list):
                    raise ValueError("expected chat.completion with choices")
                if not all(isinstance(usage.get(key), int) for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
                    raise ValueError("completion lacks integer token usage")
            self._check("non-stream chat", nonstream)

            stream_model = self._model("streaming")
            if stream_model:
                def streaming() -> None:
                    response = self._completion(stream_model, stream=True, stream_options={"include_usage": True})
                    sse_body = response.body.decode("utf-8")
                    events = [line[6:] for line in sse_body.splitlines() if line.startswith("data: ")]
                    if response.status != 200 or not events or events[-1] != "[DONE]":
                        raise ValueError("SSE must end with data: [DONE]")
                    content_type = response.headers.get("content-type", "")
                    if content_type and "text/event-stream" not in content_type.lower():
                        raise ValueError("stream response has non-SSE content type")
                    chunks = [json.loads(event) for event in events[:-1]]
                    if not chunks or not all(item.get("object") == "chat.completion.chunk" for item in chunks):
                        raise ValueError("SSE data events must be completion chunks")
                self._check("SSE streaming", streaming)
            else:
                self.report.add("SSE streaming", "skip", "no catalog model advertises streaming")

            tool_model = self._model("tools")
            if tool_model:
                def tools() -> None:
                    tool = {"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}
                    initial = self._completion(tool_model, tools=[tool], tool_choice="required")
                    first = self._json(initial)
                    calls = first.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
                    if initial.status != 200 or not calls or not isinstance(calls[0].get("id"), str):
                        raise ValueError("expected function tool call")
                    json.loads(calls[0].get("function", {}).get("arguments", ""))
                    followup = self._completion(tool_model, messages=[
                        {"role": "user", "content": "compatibility probe"},
                        {"role": "assistant", "tool_calls": calls},
                        {"role": "tool", "tool_call_id": calls[0]["id"], "content": "{\"ok\":true}"},
                    ])
                    if followup.status != 200 or self._json(followup).get("object") != "chat.completion":
                        raise ValueError("tool result follow-up did not complete")
                self._check("tool calling", tools)
            else:
                self.report.add("tool calling", "skip", "no catalog model advertises tools")

            json_model = self._model("json_schema")
            if json_model:
                def structured() -> None:
                    response = self._completion(json_model, response_format={"type": "json_object"})
                    value = self._json(response)
                    content = value.get("choices", [{}])[0].get("message", {}).get("content")
                    if response.status != 200 or not isinstance(content, str):
                        raise ValueError("expected assistant JSON content")
                    json.loads(content)
                self._check("structured JSON output", structured)
            else:
                self.report.add("structured JSON output", "skip", "no catalog model advertises json_schema")

        self._check_extended_capabilities()

        def auth_error() -> None:
            response = self.transport.request("GET", "/v1/models", self._headers(False))
            if response.status != 401 or not self._error(self._json(response)):
                raise ValueError("expected 401 OpenAI error envelope without bearer token")
        self._check("authentication error envelope", auth_error)

        if chat_model:
            def request_error() -> None:
                response = self.transport.request("POST", "/v1/chat/completions", self._headers(), {
                    "model": "invalid/does-not-exist", "messages": [{"role": "user", "content": "probe"}],
                })
                if response.status < 400 or not self._error(self._json(response)):
                    raise ValueError("expected typed error envelope for invalid model")
            self._check("request error envelope", request_error)
        return self.report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Marcel Router OpenAI compatibility.")
    parser.add_argument(
        "--base-url",
        help="OpenAI-compatible base URL, e.g. https://marcel-agent.com/api/v1",
    )
    parser.add_argument("--fixture", help="Offline ordered JSON response fixture")
    parser.add_argument("--auth-env", default="MARCEL_ROUTER_API_KEY",
                        help="environment variable containing the bearer token (never a token value)")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit JSON report")
    args = parser.parse_args(argv)
    if bool(args.base_url) == bool(args.fixture):
        parser.error("provide exactly one of --base-url or --fixture")
    if args.fixture:
        try:
            fixture = json.loads(open(args.fixture, encoding="utf-8").read())
            transport: Transport = FixtureTransport(fixture["responses"])
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            parser.error(f"invalid fixture: {exc}")
        token = os.environ.get(args.auth_env, "fixture-token")
    else:
        token = os.environ.get(args.auth_env)
        if not token:
            parser.error(f"{args.auth_env} is not set (pass its name with --auth-env)")
        transport = UrlTransport(args.base_url, args.timeout)
    report = RouterValidator(transport, token).run()
    if args.json_output:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        for check in report.checks:
            suffix = f": {check.detail}" if check.detail else ""
            print(f"{check.status.upper():4} {check.name}{suffix}")
        print(f"{'PASS' if report.ok else 'FAIL'} — {len(report.checks)} checks")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())