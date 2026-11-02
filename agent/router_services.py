"""Marcel Router service transport. Credentials never leave the configured origin."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import requests


class RouterServiceError(ValueError):
    def __init__(self, message: str, error_type: str = "provider_error", *, http_status=None, request_id=None):
        super().__init__(message)
        self.error_type = error_type
        self.http_status = http_status
        self.request_id = request_id


def service_models(rows: list, kind: str) -> list[dict]:
    """Only explicit generation capabilities qualify; vision is not generation."""
    if not isinstance(rows, list):
        return []
    result = []
    for entry in rows:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        meta = entry.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        caps = entry.get("capabilities", meta.get("capabilities", []))
        if isinstance(caps, dict):
            caps = [key for key, value in caps.items() if value is True]
        caps = {str(cap).replace("-", "_") for cap in caps} if isinstance(caps, list) else set()
        if entry.get("available") is False or meta.get("available") is False:
            continue
        if f"{kind}_generation" in caps:
            result.append({**entry, "display": entry.get("name") or entry["id"]})
    return result


class RouterServices:
    def __init__(self, config: dict | None = None, key_getter=None):
        if config is None:
            from marcel_cli.config import load_config
            config = load_config()
        marcel = config.get("marcel") or {}
        router = (marcel.get("router") or {}) if isinstance(marcel, dict) else {}
        if not isinstance(router, dict):
            raise RouterServiceError("Invalid Router configuration.", "configuration")
        if router.get("mode") != "marcel_router":
            raise RouterServiceError("Configure Marcel Router with `marcel setup`.", "auth_required")
        self.base = str(router.get("base_url") or "").rstrip("/")
        parsed = urlsplit(self.base)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or (
            not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise RouterServiceError("The configured Router URL is not a safe HTTPS endpoint.", "configuration")
        key_env = str(router.get("key_env") or "MARCEL_ROUTER_API_KEY")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
            raise RouterServiceError("Invalid Router credential reference.", "configuration")
        if key_getter is None:
            from agent.secret_scope import get_secret
            key_getter = get_secret
        saved_origin = key_getter(f"{key_env}_ORIGIN")
        if saved_origin:
            try:
                bound = urlsplit(saved_origin)
                def origin(url):
                    return (url.scheme.lower(), (url.hostname or "").lower(),
                            url.port or (443 if url.scheme == "https" else 80))
                matches = bool(bound.hostname) and origin(bound) == origin(parsed)
            except (TypeError, ValueError):
                matches = False
            if not matches:
                raise RouterServiceError(
                    "Router credential origin changed. Run `marcel setup` to enter a fresh key.",
                    "configuration",
                )
        self._key = key_getter(key_env)
        if not self._key:
            raise RouterServiceError("Marcel Router key is not configured. Run `marcel setup`.", "auth_required")
        self.config = config

    def request(self, method: str, path: str, *, payload=None, idempotency_key=None, client_request_id=None):
        if not path.startswith("/") or path.startswith("//") or ".." in path:
            raise RouterServiceError("Invalid Router service path.", "invalid_request")
        headers = {"Authorization": f"Bearer {self._key}"}
        if client_request_id:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", client_request_id):
                raise RouterServiceError("Invalid client request ID.", "invalid_request")
            headers["X-Client-Request-Id"] = client_request_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = requests.request(
                method, self.base + path, headers=headers, json=payload,
                timeout=(15, 180), allow_redirects=False,
            )
        except requests.RequestException:
            # Request exceptions can contain URLs, headers or bodies. Never echo them.
            raise RouterServiceError("Could not reach Marcel Router.", "connection_error") from None
        if not 200 <= response.status_code < 300:
            request_id = response.headers.get("x-marcel-request-id") or response.headers.get("x-request-id") or ""
            request_id = request_id if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", request_id) else None
            suffix = f" Request ID: {request_id}." if request_id else ""
            kind = "auth_required" if response.status_code in (401, 403) else (
                "payment_required" if response.status_code == 402 else "api_error")
            raise RouterServiceError(f"Marcel Router returned HTTP {response.status_code}.{suffix}", kind,
                                     http_status=response.status_code, request_id=request_id)
        return response

    def json(self, method: str, path: str, **kwargs):
        try:
            result = self.request(method, path, **kwargs).json()
        except ValueError as exc:
            if isinstance(exc, RouterServiceError):
                raise
            raise RouterServiceError("Marcel Router returned invalid JSON.", "invalid_response") from None
        if not isinstance(result, dict):
            raise RouterServiceError("Marcel Router returned an invalid response.", "invalid_response")
        return result

    def models(self, kind: str) -> list[dict]:
        if kind == "image":
            return service_models(self.json("GET", "/models").get("data", []), kind)
        if kind not in {"video", "audio"}:
            return []
        # Video is an asynchronous API, not part of the chat-completions catalog.
        parsed = urlsplit(self.base)
        prefix = parsed.path.removesuffix("/api/v1") if parsed.path.endswith("/api/v1") else ""
        url = urlunsplit((parsed.scheme, parsed.netloc, prefix + "/api/catalog", "", ""))
        try:
            response = requests.get(url, timeout=20, allow_redirects=False)
            if response.status_code != 200:
                raise RouterServiceError("Router video catalog is unavailable.", "catalog_unavailable")
            rows = response.json().get("realtime_models" if kind == "audio" else "video_models", [])
        except (requests.RequestException, ValueError, AttributeError):
            raise RouterServiceError("Router video catalog is unavailable.", "catalog_unavailable") from None
        if kind == "audio":
            return [row for row in rows if isinstance(row, dict)
                    and str(row.get("id", "")).startswith("openai/") and "realtime" in row["id"]
                    and row.get("available") is not False] if isinstance(rows, list) else []
        return service_models(rows, kind)

    def search_providers(self) -> list[str]:
        rows = self.json("GET", "/tools").get("data", [])
        if not isinstance(rows, list):
            raise RouterServiceError("Router returned an invalid search catalog.", "invalid_response")
        return [
            row["id"] for row in rows if isinstance(row, dict)
            and row.get("id") in {"brave", "exa", "tavily", "perplexity"} and row.get("available") is not False
        ]


def router_available() -> bool:
    """Cheap credential/configuration check, never a network call."""
    try:
        RouterServices()
        return True
    except (ValueError, OSError):
        return False


def configured_service_model(kind: str):
    from marcel_cli.config import load_config
    section = load_config().get(f"{kind}_gen") or {}
    return section.get("model") if isinstance(section, dict) else None
