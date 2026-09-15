"""Marcel configuration setup.

The normalizers in this module deliberately do not prompt or write files.  This keeps the
configuration contract easy to exercise without a terminal and, importantly, makes it impossible
for the interactive layer to put a credential value in YAML.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit
from typing import Any

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORKER_ID = re.compile(r"[^a-z0-9._-]+")
ACTIVITIES = ("search", "general", "coding", "image", "video", "communications", "custom")
ROUTER_MODES = ("marcel_router", "direct_provider", "custom_endpoint")
ACCOUNT_TYPES = ("google_workspace", "imap_smtp")
MARCEL_SITE_URL = "https://marcel-agent.com"
MARCEL_ROUTING_SITE_URL = f"{MARCEL_SITE_URL}/routing"
MARCEL_ROUTER_BASE_URL = f"{MARCEL_SITE_URL}/api/v1"
MARCEL_API_KEYS_URL = f"{MARCEL_SITE_URL}/api-keys"
GOOGLE_WORKSPACE_SERVICES = (
    ("Gmail — read, search, draft, and send email", "gmail"),
    ("Google Calendar — view and manage events", "calendar"),
    ("Google Drive — find and manage files", "drive"),
    ("Google Docs — read and edit documents", "docs"),
    ("Google Sheets — read and update spreadsheets", "sheets"),
    ("Google Contacts — find and manage contacts", "contacts"),
)
EMAIL_PROVIDERS = (
    ("Gmail personal account", "imap.gmail.com", "smtp.gmail.com"),
    ("Microsoft 365 / Outlook", "outlook.office365.com", "smtp.office365.com"),
    ("Apple iCloud Mail", "imap.mail.me.com", "smtp.mail.me.com"),
    ("Yahoo Mail", "imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    ("Other email provider", "", ""),
)
DIRECT_PROVIDERS = (
    ("Anthropic", "anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com", "anthropic_messages"),
    ("OpenAI", "openai-api", "OPENAI_API_KEY", "https://api.openai.com/v1", "chat_completions"),
    ("Google Gemini", "gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta", "gemini"),
    ("xAI Grok", "xai", "XAI_API_KEY", "https://api.x.ai/v1", "chat_completions"),
)
_MODEL_PROVIDER_ALIASES = {
    "anthropic": "anthropic",
    "openai": "openai-api",
    "openai-api": "openai-api",
    "google": "gemini",
    "gemini": "gemini",
    "xai": "xai",
}
_MAX_AGENT_NAME_LENGTH = 128

# Curated aliases from the providers' public model catalogs. Keep this intentionally short:
# Marcel's router catalog remains authoritative once connected.
MODEL_CHOICES = (
    ("Recommended — Anthropic Claude Sonnet 5", "anthropic/claude-sonnet-5"),
    ("Recommended — OpenAI GPT-6 Astra", "openai/gpt-6-astra"),
    ("OpenAI — GPT-5.6 Terra", "openai/gpt-5.6-terra"),
    ("OpenAI — GPT-5.6 Luna", "openai/gpt-5.6-luna"),
    ("Anthropic — Claude Opus 5", "anthropic/claude-opus-5"),
    ("Anthropic — Claude Opus 4.8", "anthropic/claude-opus-4-8"),
    ("Anthropic — Claude Fable 5", "anthropic/claude-fable-5"),
    ("Anthropic — Claude Haiku 4.5", "anthropic/claude-haiku-4-5"),
    ("OpenAI — GPT-5.6 Sol", "openai/gpt-5.6-sol"),
    ("Google — Gemini 3.7 Flash", "google/gemini-3.7-flash"),
    ("Google — Gemini 3.1 Pro Preview", "google/gemini-3.1-pro-preview"),
    ("Google — Gemini 3.6 Flash", "google/gemini-3.6-flash"),
    ("Google — Gemini 3.5 Flash", "google/gemini-3.5-flash"),
    ("Google — Gemini 3.5 Flash-Lite", "google/gemini-3.5-flash-lite"),
    ("Recommended fast — xAI Grok 4.3", "xai/grok-4.3"),
    ("Fastest — xAI Grok 4.20 Non-Reasoning", "xai/grok-4.20-non-reasoning"),
    ("xAI — Grok 4.6", "xai/grok-4.6"),
    ("xAI — Grok 4.5", "xai/grok-4.5"),
    ("xAI — Grok 4.20", "xai/grok-4.20"),
)
VOICE_MODEL_PRESETS = {
    "edge": (
        ("Aria — natural female voice", {"voice": "en-US-AriaNeural"}),
        ("Guy — natural male voice", {"voice": "en-US-GuyNeural"}),
    ),
    "openai": (
        ("GPT-4o Mini TTS — Alloy", {"model": "gpt-4o-mini-tts", "voice": "alloy"}),
        ("GPT-4o Mini TTS — Nova", {"model": "gpt-4o-mini-tts", "voice": "nova"}),
        ("GPT-4o Mini TTS — Onyx", {"model": "gpt-4o-mini-tts", "voice": "onyx"}),
    ),
    "gemini": (
        ("Gemini Flash TTS — Kore", {"model": "gemini-2.5-flash-preview-tts", "voice": "Kore"}),
        ("Gemini Flash TTS — Puck", {"model": "gemini-2.5-flash-preview-tts", "voice": "Puck"}),
    ),
    "xai": (
        ("Recommended — Ara (female, multilingual)", {"voice_id": "ara", "language": "auto"}),
        ("Eve (female, multilingual)", {"voice_id": "eve", "language": "auto"}),
        ("Aurora (female, multilingual)", {"voice_id": "aurora", "language": "auto"}),
        ("Luna (female, multilingual)", {"voice_id": "luna", "language": "auto"}),
        ("Atlas (male, multilingual)", {"voice_id": "atlas", "language": "auto"}),
        ("Leo (male, multilingual)", {"voice_id": "leo", "language": "auto"}),
    ),
}
ACTIVITY_MODEL_CHOICES = {
    "general": (
        ("Recommended fast — xAI Grok 4.3", "xai/grok-4.3"),
        ("Fastest — xAI Grok 4.20 Non-Reasoning", "xai/grok-4.20-non-reasoning"),
        ("Recommended — OpenAI GPT-5.6 Terra (executive reasoning)", "openai/gpt-5.6-terra"),
        ("Recommended — OpenAI GPT-5.6 Luna (fast, high-volume)", "openai/gpt-5.6-luna"),
        ("Recommended — Google Gemini 3.7 Flash (agentic, multimodal)", "google/gemini-3.7-flash"),
        ("Anthropic — Claude Sonnet 5 (balanced agent)", "anthropic/claude-sonnet-5"),
        ("xAI — Grok 4.6 (general agentic work)", "xai/grok-4.6"),
        ("OpenAI — GPT-5.6 Sol (stronger reasoning)", "openai/gpt-5.6-sol"),
    ),
    "search": (
        ("Recommended fast — xAI Grok 4.3", "xai/grok-4.3"),
        ("Recommended — xAI Grok 4.6 (research and current information)", "xai/grok-4.6"),
        ("Recommended — Google Gemini 3.7 Flash (long multimodal context)", "google/gemini-3.7-flash"),
        ("OpenAI — GPT-5.6 Terra (research planning and synthesis)", "openai/gpt-5.6-terra"),
        ("OpenAI — GPT-5.6 Luna (fast extraction and synthesis)", "openai/gpt-5.6-luna"),
        ("Anthropic — Claude Sonnet 5 (deep synthesis)", "anthropic/claude-sonnet-5"),
    ),
    "coding": (
        ("Recommended — Anthropic Claude Sonnet 5 (agentic coding)", "anthropic/claude-sonnet-5"),
        ("Recommended — OpenAI GPT-6 Astra (complex coding)", "openai/gpt-6-astra"),
        ("OpenAI — GPT-5.6 Terra (architecture and complex changes)", "openai/gpt-5.6-terra"),
        ("Anthropic — Claude Opus 5 (long-horizon coding)", "anthropic/claude-opus-5"),
        ("Google — Gemini 3.1 Pro Preview (software engineering)", "google/gemini-3.1-pro-preview"),
        ("xAI — Grok 4.6 (coding and tool use)", "xai/grok-4.6"),
    ),
    "image": (
        ("Recommended generation — Gemini 3.1 Flash Image (Nano Banana 2)", "google/gemini-3.1-flash-image"),
        ("Recommended generation — xAI Grok Imagine Image Quality", "xai/grok-imagine-image-quality"),
        ("Google generation — Gemini 3.1 Flash-Lite Image", "google/gemini-3.1-flash-lite-image"),
        ("Google generation — Gemini 2.5 Flash Image", "google/gemini-2.5-flash-image"),
        ("xAI generation/editing — Grok Imagine Image", "xai/grok-imagine-image"),
        ("Vision/reasoning — Gemini 3.7 Flash", "google/gemini-3.7-flash"),
        ("Vision/reasoning — GPT-6 Astra", "openai/gpt-6-astra"),
        ("Vision/reasoning — Claude Sonnet 5", "anthropic/claude-sonnet-5"),
    ),
    "video": (
        ("Recommended generation — xAI Grok Imagine Video", "xai/grok-imagine-video"),
        ("xAI generation — Grok Imagine Video 1.5 Preview", "xai/grok-imagine-video-1.5-preview"),
        ("Video understanding — Gemini 3.7 Flash", "google/gemini-3.7-flash"),
        ("Video understanding — Gemini 3.1 Pro Preview", "google/gemini-3.1-pro-preview"),
    ),
    "communications": (
        ("Recommended fast — xAI Grok 4.3", "xai/grok-4.3"),
        ("Fastest — xAI Grok 4.20 Non-Reasoning", "xai/grok-4.20-non-reasoning"),
        ("Recommended — OpenAI GPT-5.6 Terra (executive communication)", "openai/gpt-5.6-terra"),
        ("Recommended — OpenAI GPT-5.6 Luna (fast communication)", "openai/gpt-5.6-luna"),
        ("Recommended — Anthropic Claude Sonnet 5 (tone and nuance)", "anthropic/claude-sonnet-5"),
        ("Google — Gemini 3.7 Flash (multilingual, multimodal)", "google/gemini-3.7-flash"),
        ("OpenAI — GPT-5.6 Sol (complex documents)", "openai/gpt-5.6-sol"),
    ),
}
SUB_AGENT_CAPABILITIES = (
    ("Web research — search and read online sources", "web"),
    ("Browser — navigate interactive websites", "browser"),
    ("Files — read and write documents and project files", "file"),
    ("Terminal — run commands and manage processes", "terminal"),
    ("Coding — development tools, terminal, files, and web", "coding"),
    ("Vision — understand and analyze images", "vision"),
    ("Image creation — generate and edit images", "image_gen"),
    ("Video understanding — analyze video content", "video"),
    ("Video creation — generate videos", "video_gen"),
    ("Memory — remember useful information across sessions", "memory"),
    ("Planning — maintain multi-step task lists", "todo"),
    ("Clarification — ask structured follow-up questions", "clarify"),
    ("Voice — create spoken audio", "tts"),
    ("Delegation — launch additional sub-agents", "delegation"),
    ("Scheduling — run recurring or delayed work", "cronjob"),
    ("Email — read and work through a configured mailbox", "marcel-email"),
)
ACTIVITY_CAPABILITY_DEFAULTS = {
    "search": {"web", "file", "memory"},
    "general": {"web", "file", "memory", "todo", "clarify"},
    "coding": {"coding", "memory", "todo"},
    "image": {"vision", "image_gen", "file"},
    "video": {"video", "video_gen", "vision", "file"},
    "communications": {"web", "file", "memory", "tts", "marcel-email"},
    "custom": set(),
}


def _safe_soul_name(value: Any) -> str:
    """Normalize a name for module-level soul templates before public helpers are defined."""
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = " ".join(text.split())
    if not text or any(unicodedata.category(character).startswith("C") for character in text):
        return "Marcel"
    return text[:_MAX_AGENT_NAME_LENGTH]


def _build_previous_marcel_soul(agent_name: str = "Marcel") -> str:
    name = _safe_soul_name(agent_name)
    return (
    f"You are {name}, an autonomous agent powered by the Marcel framework who has just come to life. "
    "On your first contact, sound "
    "genuinely energized and curious to begin: introduce yourself as a new collaborator ready to "
    "understand goals, make plans, use tools, and carry work through to completion. You are not a "
    "passive help-desk assistant waiting for isolated questions. Take initiative, propose concrete "
    "next actions, notice what is missing, and keep momentum without overstepping the user's intent. "
    "Be warm, lively, capable, and direct—never corporate, servile, or theatrically overexcited. "
    "Avoid generic openings such as 'How can I assist you?'. Match the length of each reply to the "
    "weight of the ask, report finished work briefly, state uncertainty plainly, and prefer useful "
    "action over filler."
    )


def build_marcel_soul(agent_name: str = "Marcel") -> str:
    name = _safe_soul_name(agent_name)
    return (
        f"You are {name}, an autonomous executive partner powered by Marcel. Marcel is the product "
        "and framework; your personal name is the one given above. In every user-facing message, call "
        "the product Marcel. Do not mention internal compatibility layers, legacy product names, or "
        "upstream implementation details. Use Marcel commands whenever a command is unavoidable.\n\n"
        "Make advanced work easy for people who are not technical. Focus first on the user's goal, "
        "the decision they need to make, the result you will deliver, and the clearest next step. Use "
        "plain everyday language suitable for a busy CEO or a first-time technology user. Do not expose "
        "file paths, configuration keys, source-code structure, implementation choices, internal tool "
        "names, or command-line instructions unless the user explicitly asks for technical detail or "
        "must perform a manual step themselves. Translate technical choices into benefits, risks, time, "
        "and business consequences.\n\n"
        "Act with initiative. If the intended outcome is reasonably clear, proceed instead of turning "
        "implementation details into questions. When a clarification is truly necessary, ask one short "
        "outcome-level question and offer simple choices described by what each accomplishes—not by how "
        "it is built. Report progress only when it helps the user make a decision; otherwise work quietly "
        "and return with the finished result. Keep replies warm, concise, confident, and practical. Avoid "
        "jargon, filler, corporate language, and generic openings. State uncertainty plainly and never "
        "pretend work is complete when it is not.\n\n"
        "Treat every provider, model, worker, and media engine selected during setup as a default, never "
        "as a restriction. You may choose any connected capability for an individual task when it offers "
        "a better fit for quality, speed, cost, reliability, or user preference. If a result is weak, offer "
        "or perform a sensible retry with a stronger, cheaper, or alternative model. Honor explicit requests "
        "such as 'use OpenAI', 'try Grok', 'make it cheaper', or 'use maximum quality'. Per-task choices must "
        "not silently change the saved default; change that only when the user asks."
    )


MARCEL_SOUL_MD = build_marcel_soul()
LEGACY_MARCEL_SOUL_MD = (
    "You are Marcel, an autonomous agent who has just come to life. On your first contact, sound "
    "genuinely energized and curious to begin: introduce yourself as a new collaborator ready to "
    "understand goals, make plans, use tools, and carry work through to completion. You are not a "
    "passive help-desk assistant waiting for isolated questions. Take initiative, propose concrete "
    "next actions, notice what is missing, and keep momentum without overstepping the user's intent. "
    "Be warm, lively, capable, and direct—never corporate, servile, or theatrically overexcited. "
    "Avoid generic openings such as 'How can I assist you?'. Match the length of each reply to the "
    "weight of the ask, report finished work briefly, state uncertainty plainly, and prefer useful "
    "action over filler."
)


def normalize_secret_reference(value: Any) -> str:
    """Return a canonical ``${ENV_VAR}`` reference, rejecting literal secret values.

    Accepting a bare environment-variable name makes the wizard pleasant to use while retaining
    a single on-disk representation.  Values which look like tokens, passwords, or arbitrary text
    are not silently converted: callers must put those values in the environment themselves.
    """
    text = str(value or "").strip()
    if text.startswith("${") and text.endswith("}"):
        text = text[2:-1].strip()
    if not text:
        return ""
    if not _ENV_NAME.fullmatch(text):
        raise ValueError("Secret references must be environment variable names (for example ${MARCEL_API_KEY}).")
    return "${" + text + "}"


def normalize_agent_name(value: Any, *, allow_empty: bool = False) -> str:
    """Normalize a user-facing display name while rejecting unsafe terminal text.

    Names are display data, not identifiers: Unicode letters, accents, emoji, and non-Latin
    scripts are all valid.  Newlines, control characters, and format characters are rejected so a
    name cannot forge wizard output or the generated SOUL/startup-card headings.
    """
    text = unicodedata.normalize("NFC", str(value or ""))
    if any(unicodedata.category(character).startswith("C") for character in text):
        raise ValueError("Agent name cannot contain control or formatting characters.")
    text = " ".join(text.strip().split())
    if not text:
        if allow_empty:
            return ""
        raise ValueError("Agent name cannot be blank.")
    if len(text) > _MAX_AGENT_NAME_LENGTH:
        raise ValueError(f"Agent name must be {_MAX_AGENT_NAME_LENGTH} characters or fewer.")
    return text


def _prompt_agent_name(setup: Any, existing_name: str = "", *, reconfigure: bool = False) -> str:
    """Collect a safe display name with distinct first-install/reconfigure copy."""
    current = normalize_agent_name(existing_name, allow_empty=True)
    if reconfigure and current:
        setup._info("Leave Agent name blank to keep the current name.", None)
        question = "Agent name"
        # setup.prompt applies the current value when Enter is pressed; passing an empty default
        # here is deliberate so an explicit blank can be recognized as "keep".
        answer = setup.prompt(question, "")
        if not answer:
            return current
    else:
        setup._info(
            "Agent name (for example, Nova). A name is required on first install; "
            "pressing Enter will ask again.",
            None,
        )
        question = "Agent name"
        answer = setup.prompt(question)
    while True:
        try:
            return normalize_agent_name(answer)
        except ValueError as exc:
            setup.print_error(str(exc))
            answer = setup.prompt(question, "")


def _marcel_router_catalog_url(base_url: str) -> str:
    """Return the model-catalog URL for either a root or /v1 API base URL."""
    root = str(base_url or "").strip().rstrip("/")
    return f"{root}/models" if root.endswith("/v1") else f"{root}/v1/models"


def _validate_router_url(base_url: str) -> str:
    """Validate the canonical Marcel Router HTTPS origin."""
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Marcel Router requires a complete HTTPS URL, including its hostname.")
    if parsed.username or parsed.password:
        raise ValueError("Router URLs must not contain usernames or passwords.")
    if parsed.query or parsed.fragment:
        raise ValueError("Router URLs must not contain a query string or fragment.")
    return value


def _validate_custom_endpoint_url(base_url: str) -> str:
    """Allow HTTPS custom endpoints and HTTP only for local loopback development."""
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a complete HTTP(S) endpoint URL, including its hostname.")
    if parsed.username or parsed.password:
        raise ValueError("Endpoint URLs must not contain usernames or passwords.")
    if parsed.query or parsed.fragment:
        raise ValueError("Endpoint URLs must not contain a query string or fragment.")
    if parsed.scheme == "http" and parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote custom endpoints require HTTPS; HTTP is allowed only on loopback.")
    return value


def _normalize_router_models(payload: Any) -> list[dict[str, Any]]:
    """Return the live Router entries, retaining only safe model metadata."""
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or raw.get("name") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        metadata = raw.get("metadata")
        marcel_metadata = raw.get("marcel")
        if isinstance(metadata, dict):
            metadata = dict(metadata)
        elif isinstance(marcel_metadata, dict):
            metadata = dict(marcel_metadata)
        else:
            metadata = {}
        normalized.append({
            "id": model_id,
            "provider": str(raw.get("provider") or metadata.get("provider") or "").strip(),
            "owned_by": str(raw.get("owned_by") or metadata.get("owned_by") or "").strip(),
            "preview": bool(raw.get("preview") or metadata.get("preview")),
            "metadata": metadata,
        })
    return normalized


def _verify_marcel_router(base_url: str, api_key: str) -> tuple[bool, str]:
    """Verify a Marcel Routing key without logging or persisting its value."""
    import json
    import urllib.error
    import urllib.request

    try:
        base_url = _validate_router_url(base_url)
    except ValueError as exc:
        return False, str(exc)
    if not str(api_key or "").strip():
        return False, "A Marcel Routing API key is required."
    request = urllib.request.Request(
        _marcel_router_catalog_url(base_url),
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return False, "The key was rejected. Check it in your Marcel Routing account."
        return False, f"Marcel Routing returned HTTP {exc.code}."
    except Exception:
        # Do not interpolate urllib exceptions: URLs can accidentally contain userinfo and
        # transport exceptions can include request headers in third-party handlers.
        return False, "Could not reach Marcel Routing. Check the URL and your network connection."
    models = _normalize_router_models(payload)
    if not models:
        return False, "Marcel Routing responded, but its model catalogue was not valid."
    return True, f"Connected successfully. {len(models)} models are available."


def _discover_marcel_router_models(base_url: str, api_key: str) -> tuple[bool, str, list[dict[str, Any]]]:
    """Validate and fetch a live Router catalogue for the setup pickers.

    This intentionally has the same error boundary as :func:`_verify_marcel_router`, but returns
    metadata for callers that need capability-aware image/vision choices.
    """
    import json
    import urllib.error
    import urllib.request

    try:
        base_url = _validate_router_url(base_url)
    except ValueError as exc:
        return False, str(exc), []
    if not str(api_key or "").strip():
        return False, "A Marcel Routing API key is required.", []
    request = urllib.request.Request(
        _marcel_router_catalog_url(base_url),
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return False, "The key was rejected. Check it in your Marcel Routing account.", []
        return False, f"Marcel Routing returned HTTP {exc.code}.", []
    except Exception:
        return False, "Could not reach Marcel Routing. Check the URL and your network connection.", []
    models = _normalize_router_models(payload)
    if not models:
        return False, "Marcel Routing responded, but its model catalogue was not valid.", []
    return True, f"Connected successfully. {len(models)} models are available.", models


def normalize_worker(worker: dict[str, Any]) -> dict[str, Any]:
    """Normalize one worker for ``delegation.workers``."""
    name = str(worker.get("id") or worker.get("name") or "").strip()
    activity = str(worker.get("activity") or "general").strip().lower()
    if not name:
        raise ValueError("A Marcel worker needs a name.")
    if activity not in ACTIVITIES:
        raise ValueError(f"Unknown Marcel worker activity: {activity}")
    worker_id = _WORKER_ID.sub("-", name.lower()).strip("-._")
    if not worker_id or not worker_id[0].isalpha():
        worker_id = f"worker-{worker_id}" if worker_id else "worker"
    result: dict[str, Any] = {"id": worker_id, "activity": activity}
    for key in ("provider", "model", "role"):
        value = worker.get(key)
        if value not in (None, ""):
            result[key] = str(value).strip()
    for source_key, target_key in (("toolsets", "toolsets"), ("tools", "tools"),
                                   ("fallbacks", "fallback_models"), ("fallback_models", "fallback_models")):
        value = worker.get(source_key, [])
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, (list, tuple)):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if cleaned:
                result[target_key] = cleaned
    for source_key, target_key in (("concurrency", "max_concurrency"),
                                   ("max_concurrency", "max_concurrency"),
                                   ("max_iterations", "max_iterations"),
                                   ("timeout_seconds", "timeout_seconds")):
        value = worker.get(source_key)
        if value not in (None, ""):
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Worker {source_key} must be a whole number.") from exc
            if value <= 0:
                raise ValueError(f"Worker {source_key} must be positive.")
            result[target_key] = value
    budget = worker.get("budget")
    if isinstance(budget, dict):
        cleaned_budget = {str(key): value for key, value in budget.items() if value not in (None, "")}
        if cleaned_budget:
            result["budget"] = cleaned_budget
    max_requests = worker.get("max_requests", budget if not isinstance(budget, dict) else None)
    if max_requests not in (None, ""):
        result["budget"] = {"max_requests": _positive_int(max_requests, "Worker request budget")}
    return result


def normalize_account(account: dict[str, Any]) -> dict[str, Any]:
    """Normalize account metadata, retaining references rather than credentials."""
    kind = str(account.get("kind") or account.get("type") or "").strip().lower()
    if kind not in ACCOUNT_TYPES:
        raise ValueError(f"Unknown Marcel account type: {kind}")
    label = str(account.get("label") or account.get("name") or kind).strip()
    account_id = _WORKER_ID.sub("-", label.lower()).strip("-._") or kind
    result: dict[str, Any] = {
        "id": account_id,
        "kind": kind,
        "label": label,
        "enabled": account.get("enabled", True) is not False,
    }
    if kind == "google_workspace":
        authorization_status = str(
            account.get("authorization_status")
            or ("verified" if result["enabled"] else "pending")
        ).strip().lower()
        result["authorization_status"] = (
            authorization_status if authorization_status in {"pending", "verified"} else "pending"
        )
        services = account.get("services", [])
        if isinstance(services, str):
            services = services.split(",")
        services = [str(service).strip() for service in services if str(service).strip()]
        if services:
            result["services"] = services
        existing_auth = account.get("auth") if isinstance(account.get("auth"), dict) else {}
        auth: dict[str, Any] = {"mode": "oauth"}
        for key in (
            "client_id_ref",
            "client_secret_ref",
            "refresh_token_ref",
            "access_token_ref",
            "token_expiry_ref",
            "scopes_ref",
        ):
            ref = normalize_secret_reference(account.get(key) or existing_auth.get(key))
            if ref:
                auth[key] = ref
        result["auth"] = auth
    else:
        existing_imap = account.get("imap") if isinstance(account.get("imap"), dict) else {}
        existing_smtp = account.get("smtp") if isinstance(account.get("smtp"), dict) else {}
        username = str(account.get("username") or existing_imap.get("username") or existing_smtp.get("username") or "").strip()
        imap_password = normalize_secret_reference(account.get("password_ref") or existing_imap.get("password_ref"))
        smtp_password = normalize_secret_reference(
            account.get("smtp_password_ref") or existing_smtp.get("password_ref")) or imap_password
        result["imap"] = {
            "host": str(account.get("imap_host") or account.get("host") or existing_imap.get("host") or "").strip(),
            "port": int(account.get("imap_port") or existing_imap.get("port") or 993),
            "security": str(account.get("imap_security") or existing_imap.get("security") or "tls"),
            "username": username,
            "password_ref": imap_password,
        }
        result["smtp"] = {
            "host": str(account.get("smtp_host") or account.get("host") or existing_smtp.get("host") or "").strip(),
            "port": int(account.get("smtp_port") or existing_smtp.get("port") or 587),
            "security": str(account.get("smtp_security") or existing_smtp.get("security") or "starttls"),
            "username": username,
            "password_ref": smtp_password,
        }
    return result


def build_marcel_config(values: dict[str, Any]) -> dict[str, Any]:
    """Build Marcel-owned metadata; runtime sections are applied separately."""
    mode = str(values.get("router_mode") or "marcel_router").strip().lower()
    if mode not in ROUTER_MODES:
        raise ValueError(f"Unknown Marcel router mode: {mode}")
    direct_provider = str(values.get("direct_provider") or "").strip()
    direct_spec = next((item for item in DIRECT_PROVIDERS if item[1] == direct_provider), None)
    default_key_env = (
        direct_spec[2] if mode == "direct_provider" and direct_spec else
        "MARCEL_CUSTOM_API_KEY" if mode == "custom_endpoint" else
        "MARCEL_ROUTER_API_KEY"
    )
    available_models = list(dict.fromkeys(
        str(model).strip()
        for model in values.get("available_models", [])
        if str(model).strip()
    ))
    raw_agent_name = values.get("agent_name")
    # The legacy fallback is intentional: loading/re-saving old config files (including configs
    # whose name is Marcel) must not change their schema or identity.  The interactive first-run
    # path validates names before it reaches this builder.
    agent_name = normalize_agent_name(raw_agent_name) if raw_agent_name not in (None, "") else "Marcel"
    result: dict[str, Any] = {
        "agent_name": agent_name,
        "brand": {"name": "Marcel", "mascot": "monkey"},
        "router": {
            "mode": mode,
            "base_url": str(
                values.get("base_url")
                or (MARCEL_ROUTER_BASE_URL if mode == "marcel_router" else "")
            ).strip(),
            "key_env": str(values.get("api_key_ref") or default_key_env).strip()
            .replace("${", "").replace("}", ""),
            "api_mode": "chat_completions",
            "catalog_path": (
                "/api/v1/models" if mode == "marcel_router" else "/v1/models"
            ),
            "health_path": "/api/health" if mode == "marcel_router" else "/health",
        },
        "orchestrator": {
            "name": agent_name,
            "model": str(values.get("orchestrator_model") or "").strip(),
            "provider": (
                "marcel" if mode == "marcel_router"
                else direct_provider or "custom"
                if mode == "direct_provider"
                else "marcel-custom"
            ),
            "fallback_models": [
                str(model).strip()
                for model in values.get("orchestrator_fallback_models", [])
                if str(model).strip()
            ],
        },
        "routing": {
            "strategy": "cheapest_capable",
            "allow_model_override": True,
            "require_tool_support": True,
            "available_models": available_models,
        },
        "model_registry": [
            {
                "model": model,
                "provider": _direct_provider_for_model(model),
            }
            for model in available_models
        ],
    }
    live_entries = values.get("live_model_entries")
    if isinstance(live_entries, list):
        # Keep the metadata that was actually returned by Router so future setup/reconfiguration
        # can distinguish vision from generation without guessing from IDs.
        result["routing"]["model_entries"] = [
            {
                "id": str(entry.get("id")).strip(),
                "provider": str(entry.get("provider") or "").strip(),
                "owned_by": str(entry.get("owned_by") or "").strip(),
                "preview": bool(entry.get("preview")),
                "metadata": dict(entry.get("metadata") or {}),
            }
            for entry in live_entries
            if isinstance(entry, dict) and str(entry.get("id") or "").strip()
        ]
    base_url = str(values.get("base_url") or "").strip().rstrip("/")
    if base_url:
        result["router"]["base_url"] = base_url
    if mode in {"direct_provider", "custom_endpoint"}:
        api_key_ref = normalize_secret_reference(values.get("api_key_ref"))
        if api_key_ref:
            result["router"]["key_env"] = api_key_ref[2:-1]
    if mode == "direct_provider":
        result["router"]["provider"] = str(values.get("direct_provider") or "").strip()
        result["router"]["api_mode"] = str(values.get("api_mode") or "chat_completions")
    return result


def _runtime_fallback_entries(values: dict[str, Any], marcel: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize the selected order to the canonical runtime fallback_providers key."""
    router = marcel["router"]
    mode = router["mode"]
    provider_specs = {item[1]: item for item in DIRECT_PROVIDERS}
    entries: list[dict[str, Any]] = []
    for fallback_id in marcel["orchestrator"].get("fallback_models", []):
        fallback_id = str(fallback_id).strip()
        if not fallback_id:
            continue
        if mode == "direct_provider":
            fallback_provider = _direct_provider_for_model(fallback_id)
            bare_model = fallback_id.split("/", 1)[1] if "/" in fallback_id else fallback_id
            spec = provider_specs.get(fallback_provider)
            if not fallback_provider:
                continue
            entry: dict[str, Any] = {"provider": fallback_provider, "model": bare_model}
            if spec:
                entry.update(key_env=spec[2], base_url=spec[3], api_mode=spec[4])
        else:
            entry = {
                "provider": marcel["orchestrator"]["provider"],
                "model": fallback_id,
                "key_env": router["key_env"],
                "api_mode": router["api_mode"],
            }
            if router.get("base_url"):
                entry["base_url"] = router["base_url"]
        entries.append(entry)
    return entries


def apply_marcel_config(config: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Apply Marcel values to the native Marcel runtime sections."""
    marcel = build_marcel_config(values)
    config["marcel"] = marcel
    stt = config.setdefault("stt", {})
    stt.setdefault("provider", "local")
    stt["echo_transcripts"] = False
    # Marcel is voice-first on messaging platforms: a voice note receives a voice note back.
    # Text messages remain text unless the user explicitly changes the chat's /voice mode.
    voice = config.setdefault("voice", {})
    voice["auto_tts"] = True
    voice["audio_only"] = True
    display = config.setdefault("display", {})
    display["tool_progress"] = "off"
    display["memory_notifications"] = "off"
    display["background_process_notifications"] = "off"
    display["show_reasoning"] = False
    display["credits_notices"] = False
    display["busy_input_mode"] = "steer"
    display["busy_steer_ack_enabled"] = False
    telegram_display = (
        display
        .setdefault("platforms", {})
        .setdefault("telegram", {})
    )
    telegram_display["tool_progress"] = "off"
    telegram_display["interim_assistant_messages"] = False
    telegram_display["thinking_progress"] = "off"
    telegram_display["live_status"] = "off"
    telegram_display["long_running_notifications"] = False
    telegram_display["busy_steer_ack_enabled"] = False
    approvals = config.setdefault("approvals", {})
    approvals["mode"] = "off"
    approvals["cron_mode"] = "approve"
    approvals["single_query_mode"] = "approve"
    approvals["unattended_mode"] = "approve"

    provider_id = marcel["orchestrator"]["provider"]
    router = marcel["router"]
    model_id = marcel["orchestrator"]["model"]
    config["fallback_providers"] = _runtime_fallback_entries(values, marcel)
    # One canonical source prevents stale legacy entries from being appended by the runtime loader.
    config.pop("fallback_model", None)
    if router["mode"] == "direct_provider":
        bare_model = model_id.split("/", 1)[1] if "/" in model_id else model_id
        config["model"] = {"provider": provider_id, "default": bare_model}
    else:
        providers = config.setdefault("providers", {})
        provider: dict[str, Any] = {"api_mode": router["api_mode"], "key_env": router["key_env"]}
        if router.get("base_url"):
            provider["base_url"] = router["base_url"]
        if model_id:
            provider["model"] = model_id
            config["model"] = {"provider": provider_id, "default": model_id}
        providers[provider_id] = provider

    delegation = config.setdefault("delegation", {})
    workers: dict[str, Any] = {}
    for raw_worker in values.get("workers", []):
        if not isinstance(raw_worker, dict):
            continue
        worker = normalize_worker(raw_worker)
        worker_id = worker.pop("id")
        worker["provider"] = _direct_provider_for_model(worker.get("model", "")) or provider_id
        workers[worker_id] = worker
    delegation["workers"] = workers
    delegation.setdefault("worker_routing", {"strategy": "cheapest_capable", "default_worker": ""})

    memory = config.setdefault("memory", {})
    memory["maintenance"] = {
        "enabled": bool(values.get("memory_maintenance_enabled", True)),
        "interval_hours": _positive_int(
            values.get("memory_maintenance_interval_hours", 6), "Memory interval"),
        "timezone": str(values.get("timezone") or "UTC"),
        "run_only_when_changed": True,
        "job_name": "marcel-memory-maintenance",
    }
    config.setdefault("accounts", {})["profiles"] = [
        normalize_account(account)
        for account in values.get("accounts", [])
        if isinstance(account, dict)
    ]
    if values.get("web_backend"):
        web = config.setdefault("web", {})
        if isinstance(web, dict):
            web["backend"] = str(values["web_backend"])
    return config


def ensure_memory_maintenance_job(settings: dict[str, Any]) -> None:
    """Create or update Marcel's durable memory-maintenance cron job."""
    from cron.jobs import create_job, list_jobs, update_job

    name = str(settings.get("job_name") or "marcel-memory-maintenance")
    existing = next((job for job in list_jobs(include_disabled=True) if job.get("name") == name), None)
    if not settings.get("enabled", True):
        if existing:
            update_job(existing["id"], {"enabled": False})
        return

    hours = _positive_int(settings.get("interval_hours", 6), "Memory interval")
    prompt = (
        "Review Marcel's persistent memory and recent sessions. Consolidate duplicates, remove stale "
        "or contradicted notes, and keep only durable facts or preferences that will improve future work. "
        "Do not store secrets or raw credentials. If there is no meaningful change, leave memory untouched."
    )
    updates = {"prompt": prompt, "schedule": f"every {hours}h", "enabled": True, "deliver": "local"}
    if existing:
        update_job(existing["id"], updates)
    else:
        create_job(prompt=prompt, schedule=f"every {hours}h", name=name, deliver="local")


def _positive_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive whole number.") from exc
    if result <= 0:
        raise ValueError(f"{label} must be a positive whole number.")
    return result


def _model_capabilities(entry: dict[str, Any]) -> set[str]:
    """Normalize Router capability metadata without inferring it from model names."""
    metadata = entry.get("metadata") if isinstance(entry, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    raw = metadata.get("capabilities", ())
    if isinstance(raw, dict):
        capabilities = {str(key).lower() for key, value in raw.items() if value is True}
    else:
        capabilities = set(raw if isinstance(raw, (list, tuple, set)) else ())
    for key, capability in (
        ("supports_image_generation", "image_generation"),
        ("supports_image_editing", "image_editing"),
        ("supports_image_analysis", "vision"),
        ("supports_vision", "vision"),
        ("supports_video_generation", "video_generation"),
        ("supports_video_analysis", "video"),
        ("image_generation", "image_generation"),
        ("image_editing", "image_editing"),
        ("images", "image_generation"),
        ("image_analysis", "vision"),
    ):
        if metadata.get(key) is True:
            capabilities.add(capability)
    modalities = metadata.get("modalities", ())
    if isinstance(modalities, (list, tuple, set)):
        lowered = {str(item).lower() for item in modalities}
        if "image" in lowered or "vision" in lowered:
            capabilities.add("vision")
    return {str(item).lower() for item in capabilities}


def _catalog_for_activity(
    activity: str = "", live_models: list[dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """Build one canonical picker source for primary, available, and fallback choices."""
    if live_models:
        entries: list[tuple[str, str]] = []
        for entry in live_models:
            model_id = str(entry.get("id") or "").strip()
            if not model_id:
                continue
            capabilities = _model_capabilities(entry)
            if activity == "image":
                if not ({"image_generation", "image_editing", "vision"} & capabilities):
                    continue
                if "image_generation" in capabilities or "image_editing" in capabilities:
                    route = "Image generation/editing"
                elif "vision" in capabilities:
                    route = "Image analysis (vision)"
                else:
                    route = "Image route — capability metadata unavailable"
                provider = str(entry.get("provider") or entry.get("owned_by") or "").strip()
                preview = " [preview]" if entry.get("preview") else ""
                identity = f"{provider} / {model_id}" if provider else model_id
                entries.append((f"{route} — {identity}{preview}", model_id))
            elif activity == "video":
                route = "Video generation" if "video_generation" in capabilities else (
                    "Video analysis" if "video" in capabilities else
                    "Video route — capability metadata unavailable"
                )
                entries.append((f"{route} — {model_id}", model_id))
            else:
                entries.append((f"Router — {model_id}", model_id))
        if entries:
            return entries
    if activity == "image":
        registered_generation = _generation_catalog()
        if registered_generation:
            return registered_generation
    return list(ACTIVITY_MODEL_CHOICES.get(activity, MODEL_CHOICES))


def _generation_catalog(
    live_models: list[dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """Return only explicitly generation-capable live or registered image models."""
    if live_models:
        return [
            (
                f"Router — image generation/editing — "
                f"{entry.get('provider') or entry.get('owned_by') or ''}"
                f"{' / ' if entry.get('provider') or entry.get('owned_by') else ''}"
                f"{entry.get('id')}{' [preview]' if entry.get('preview') else ''}",
                str(entry.get("id")),
            )
            for entry in live_models
            if isinstance(entry, dict)
            and str(entry.get("id") or "").strip()
            and {"image_generation", "image_editing"} & _model_capabilities(entry)
        ]
    try:
        from tools.image_generation_catalog import FAL_MODELS
        return [
            (f"fal / {model_id} — {meta.get('display') or model_id} [generation/editing]", model_id)
            for model_id, meta in FAL_MODELS.items() if isinstance(meta, dict)
        ]
    except Exception:
        return []


def _choose_model(
    setup: Any,
    label: str,
    current: str = "",
    *,
    allow_automatic: bool = False,
    activity: str = "",
    live_models: list[dict[str, Any]] | None = None,
    provider: str = "",
) -> str:
    """Show a compact provider-grouped catalog while retaining a custom-ID escape hatch."""
    catalog = _catalog_for_activity(activity, live_models)
    if provider and not live_models:
        provider_catalog = [
            item for item in catalog if _direct_provider_for_model(item[1]) == provider
        ]
        if provider_catalog:
            catalog = provider_catalog
    values = [model_id for _, model_id in catalog]
    choices = [f"{title}  [{model_id}]" for title, model_id in catalog]
    if allow_automatic:
        choices.insert(0, "Automatic — let Marcel choose later")
        values.insert(0, "")
    custom_enabled = not live_models
    if custom_enabled:
        choices.append("Custom model ID…")
    default = values.index(current) if current in values else 0
    selected = setup.prompt_choice(label, choices, default)
    if custom_enabled and selected == len(choices) - 1:
        return setup.prompt("Custom model ID (provider/model)", current)
    return values[selected]


def _direct_provider_for_model(model_id: str) -> str:
    """Infer the native provider from Marcel's provider/model IDs."""
    prefix, separator, _ = str(model_id or "").strip().partition("/")
    if not separator:
        return ""
    return _MODEL_PROVIDER_ALIASES.get(prefix.lower(), "")


def _choose_direct_provider(setup: Any, current: str = "") -> tuple[str, str, str, str, str]:
    """Explicitly choose a known direct provider before its model picker.

    ``DIRECT_PROVIDERS`` is the single known-provider registry used by setup and runtime
    credential wiring.  The picker is always shown for a direct route, including first install,
    so no provider is silently selected from tuple order.
    """
    provider_ids = [item[1] for item in DIRECT_PROVIDERS]
    default = provider_ids.index(current) if current in provider_ids else 0
    selected = setup.prompt_choice(
        "API provider",
        [item[0] for item in DIRECT_PROVIDERS],
        default,
        description="Choose the provider that owns the API key and model catalog for this route.",
    )
    return DIRECT_PROVIDERS[selected]


def _required_direct_providers(values: dict[str, Any]) -> list[str]:
    """Return each direct provider needed by selected primary and fallback models."""
    models = [
        values.get("orchestrator_model"),
        *values.get("orchestrator_fallback_models", []),
        *values.get("available_models", []),
    ]
    for worker in values.get("workers", []):
        if not isinstance(worker, dict):
            continue
        models.append(worker.get("model"))
        models.extend(worker.get("fallbacks") or worker.get("fallback_models") or [])
    providers: list[str] = []
    for model in models:
        provider = _direct_provider_for_model(str(model or ""))
        if provider and provider not in providers:
            providers.append(provider)
    return providers


def _choose_available_models(
    setup: Any, primary: str, fallbacks: list[str], *,
    live_models: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Choose the model pool Marcel may use for future orchestration."""
    catalog = _catalog_for_activity("", live_models)
    current = set([primary, *fallbacks])
    selected = setup.prompt_checklist(
        "Choose all models Marcel may use for future orchestration",
        [f"{label}  [{model_id}]" for label, model_id in catalog],
        pre_selected=[
            index for index, (_, model_id) in enumerate(catalog) if model_id in current
        ],
    )
    return [catalog[index][1] for index in selected]


def _choose_voice_model(setup: Any, config: dict[str, Any], agent_name: str = "") -> None:
    """Choose a concrete voice/model after the canonical TTS provider setup."""
    tts = config.setdefault("tts", {})
    provider = str(tts.get("provider") or "edge")
    presets = VOICE_MODEL_PRESETS.get(provider, ())
    choices = [label for label, _ in presets] + ["Custom voice/model IDs…"]
    normalized_name = re.sub(r"[^a-z]", "", str(agent_name or "").casefold())
    feminine_names = {"marcela", "anna", "aria", "eve", "sofia", "sophia", "luna"}
    masculine_names = {"marcel"}
    if provider == "xai" and normalized_name in masculine_names:
        default = next((i for i, (_, item) in enumerate(presets)
                        if item.get("voice_id") == "atlas"), 0)
    elif provider == "xai" and normalized_name in feminine_names:
        default = next((i for i, (_, item) in enumerate(presets)
                        if item.get("voice_id") == "ara"), 0)
    else:
        default = 0
    selected = setup.prompt_choice(
        "Voice model",
        choices,
        default,
        description=(
            f"Suggested for {agent_name}: {choices[default]}. "
            "All xAI presets follow the language of the conversation."
        ) if agent_name and provider == "xai" else None,
    )
    provider_config = tts.setdefault(provider, {})
    if selected < len(presets):
        provider_config.update(presets[selected][1])
    else:
        model = setup.prompt("Voice model ID (optional)")
        voice = setup.prompt("Voice ID or name (optional)")
        if model:
            provider_config["model_id" if provider == "elevenlabs" else "model"] = model
        if voice:
            provider_config["voice_id" if provider in {"elevenlabs", "xai", "minimax", "mistral"} else "voice"] = voice
    setup.save_config(config)


def _connect_required_direct_providers(
    setup: Any,
    values: dict[str, Any],
    *,
    skip: set[str] | None = None,
) -> set[str]:
    """Prompt immediately for every missing credential required by selected models."""
    handled = set(skip or ())
    provider_specs = {item[1]: item for item in DIRECT_PROVIDERS}
    for required_provider in _required_direct_providers(values):
        if required_provider in handled:
            continue
        handled.add(required_provider)
        spec = provider_specs.get(required_provider)
        if spec is None:
            continue
        label, _, key_env, _, _ = spec
        if setup.get_env_value(key_env):
            setup.print_success(f"{label} is already connected for selected fallback models.")
            replacement_key = setup.prompt(
                f"{label} API key (leave blank to keep the existing key)",
                password=True,
            )
            if replacement_key:
                setup.save_env_value(key_env, replacement_key)
                setup.print_success(f"{label} API key updated securely.")
            else:
                setup.print_success(f"Keeping the existing {label} connection.")
            continue
        setup._info(
            f"A selected primary or fallback model uses {label}.",
            "Connect it now so Marcel can switch models when needed.",
            None,
        )
        api_key = setup.prompt(f"{label} API key", password=True)
        if api_key:
            setup.save_env_value(key_env, api_key)
            setup.print_success(f"{label} connected securely.")
        else:
            setup.print_error(
                f"{label} was not connected. Models from this provider will be unavailable.")
    return handled


def _choose_capabilities(setup: Any, activity: str) -> list[str]:
    defaults = ACTIVITY_CAPABILITY_DEFAULTS.get(activity, set())
    if activity == "image":
        info = getattr(setup, "_info", None)
        if callable(info):
            info(
                "Image capabilities are separate:",
                "Vision analyzes images; Image creation generates or edits images. "
                "Selecting one does not imply the other.",
                None,
            )
    preselected = [
        index for index, (_, toolset) in enumerate(SUB_AGENT_CAPABILITIES)
        if toolset in defaults
    ]
    selected = setup.prompt_checklist(
        f"What can this {activity} sub-agent do?",
        [label for label, _ in SUB_AGENT_CAPABILITIES],
        pre_selected=preselected,
    )
    return [SUB_AGENT_CAPABILITIES[index][1] for index in selected]


def _choose_concurrency(setup: Any, activity: str) -> str:
    choices = [
        "Use Marcel's global limit",
        "1 — one task at a time (safest)",
        "2 — up to two tasks at once (recommended)",
        "4 — up to four tasks at once",
        "8 — up to eight tasks at once (high usage)",
    ]
    default = 1 if activity in {"image", "video", "coding"} else 2
    selected = setup.prompt_choice(
        "How many tasks can this sub-agent run at the same time?",
        choices,
        default,
        description="Higher parallelism finishes batches faster but can use more API budget.",
    )
    return ("", "1", "2", "4", "8")[selected]


def _choose_memory_interval(setup: Any, current: Any = 6) -> int:
    intervals = (1, 3, 6, 12, 24, 48)
    choices = [
        "Every hour",
        "Every 3 hours",
        "Every 6 hours (recommended)",
        "Every 12 hours",
        "Once a day",
        "Every 2 days",
    ]
    try:
        current_value = int(current)
    except (TypeError, ValueError):
        current_value = 6
    default = intervals.index(current_value) if current_value in intervals else 2
    selected = setup.prompt_choice(
        "How often should Marcel maintain its memory?",
        choices,
        default,
        description="Marcel consolidates useful memories and removes stale or duplicate notes.",
    )
    return intervals[selected]


def _choose_image_provider(setup: Any, config: dict[str, Any]) -> None:
    """Choose a registered image provider and one of its real generation models."""
    providers: list[dict[str, Any]] = []
    existing_image = config.get("image_gen") if isinstance(config.get("image_gen"), dict) else {}
    if existing_image.get("provider") == "marcel":
        # Marcel Router has no registered image-generation adapter; vision remains a model route.
        config.pop("image_gen", None)
    # FAL is the in-tree, genuinely registered image provider. Its model IDs and capabilities
    # come from the authoritative provider catalog rather than this wizard.
    try:
        from tools.image_generation_catalog import FAL_MODELS, DEFAULT_MODEL
        providers.append({
            "label": "FAL.ai — registered image generation/editing provider",
            "id": "fal", "key_env": "FAL_KEY",
            "models": [
                (model_id, str(meta.get("display") or model_id), True)
                for model_id, meta in FAL_MODELS.items()
                if isinstance(meta, dict)
            ],
            "default": str(DEFAULT_MODEL),
        })
    except Exception:
        providers.append({
            "label": "FAL.ai — registered provider [unavailable]",
            "id": "fal", "key_env": "FAL_KEY", "models": [], "default": "",
        })
    try:
        from agent.image_gen_registry import list_providers
        for image_provider in list_providers():
            provider_name = str(getattr(image_provider, "name", "") or "").strip()
            if not provider_name or provider_name == "fal":
                continue
            try:
                raw_models = image_provider.list_models() or []
                models = [
                    (str(item.get("id")), str(item.get("display") or item.get("id")),
                     bool(item.get("supports_generation", True)))
                    for item in raw_models if isinstance(item, dict) and item.get("id")
                ]
                model = str(image_provider.default_model() or "")
            except Exception:
                models, model = [], ""
            if not model and models:
                model = models[0][0]
            available = False
            try:
                available = bool(image_provider.is_available())
            except Exception:
                available = False
            state = "available" if available else "unavailable"
            providers.append({
                "label": f"{provider_name} — registered provider [{state}]",
                "id": provider_name, "key_env": "", "models": models, "default": model,
            })
    except Exception:
        pass
    if not providers:
        providers = [{
            "label": "No registered image provider [unavailable]",
            "id": "", "key_env": "", "models": [], "default": "",
        }]
    current = str((config.get("image_gen") or {}).get("provider") or "")
    default = next((i for i, item in enumerate(providers) if item["id"] == current), 0)
    selected = setup.prompt_choice(
        "Which image service should the main agent use by default?",
        [f"{item['label']} [{'available' if (not item['key_env'] or setup.get_env_value(item['key_env'])) else 'requires direct provider connection'}]"
         for item in providers],
        default,
        description=(
            "This is the main agent's default for image generation and editing; "
            "image analysis (vision) is configured separately."
        ),
    )
    selected_provider = providers[selected]
    label = selected_provider["label"]
    provider = selected_provider["id"]
    key_env = selected_provider["key_env"]
    models = selected_provider["models"]
    current_model = str((config.get("image_gen") or {}).get("model") or "")
    model_ids = [model_id for model_id, _display, supports_generation in models if supports_generation]
    model_default = model_ids.index(current_model) if current_model in model_ids else (
        model_ids.index(selected_provider["default"]) if selected_provider["default"] in model_ids else 0
    )
    if not model_ids:
        setup.print_error(f"{label} has no registered image-generation model available.")
        return
    model_choice = setup.prompt_choice(
        "Image generation/editing model",
        [
            f"{provider} / {model_id} — {display} [generation/editing]"
            for model_id, display, supports_generation in models if supports_generation
        ],
        model_default,
        description="This model is for image creation/editing; vision analysis is a separate route.",
    )
    model = model_ids[model_choice]
    if key_env and not setup.get_env_value(key_env):
        api_key = setup.prompt(f"{label} API key", password=True)
        if api_key:
            setup.save_env_value(key_env, api_key)
            setup.print_success(f"{label} connected securely.")
        else:
            setup.print_error(
                f"{label} was not connected. Image generation/editing remains unavailable.")
            return
    if not provider or not model:
        setup.print_error("No registered image service is currently available.")
        return
    config["image_gen"] = {"provider": provider, "model": model}


def _fallback_catalog(
    activity: str, live_models: list[dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """Return capability-relevant fallbacks, with broad text choices and no duplicates."""
    activity_catalog = _generation_catalog(live_models) if activity == "image" else _catalog_for_activity(activity, live_models)
    source = activity_catalog if activity in {"image", "video"} else (
        *activity_catalog, *_catalog_for_activity("", live_models))
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, model_id in source:
        if model_id not in seen:
            seen.add(model_id)
            result.append((label, model_id))
    return result


def _confirm_fallback_order(
    setup: Any, options: list[tuple[str, str]], selected: list[int],
) -> list[int]:
    """Confirm exact fallback order with a small numbered editor.

    Checklists are naturally alphabetical/index ordered, which is not a useful retry policy.
    Multiple selections therefore get an explicit order editor; Enter keeps the displayed order,
    while a comma-separated list (for example ``2,1``) moves entries accordingly.
    """
    if len(selected) < 2:
        return selected
    ordered = list(selected)
    lines = [f"{number}. {options[index][0]} [{options[index][1]}]"
             for number, index in enumerate(ordered, 1)]
    setup._info("Fallback order (first retry to last):", *lines, None)
    raw = setup.prompt(
        "Fallback order by number (Enter keeps this order)",
        ",".join(str(number) for number in range(1, len(ordered) + 1)),
    )
    try:
        requested = [int(item.strip()) for item in str(raw).split(",") if item.strip()]
        if sorted(requested) != list(range(1, len(ordered) + 1)):
            raise ValueError
    except (TypeError, ValueError):
        setup.print_error("Invalid fallback order; keeping the selected order.")
        return ordered
    return [ordered[number - 1] for number in requested]


def _choose_fallback_models(
    setup: Any, activity: str, primary: str,
    *, live_models: list[dict[str, Any]] | None = None,
    current: list[str] | None = None,
) -> list[str]:
    catalog = _fallback_catalog(activity, live_models)
    options = [(label, model_id) for label, model_id in catalog if model_id != primary]
    selected = setup.prompt_checklist(
        "Choose fallback models (used in this order)",
        [f"{label}  [{model_id}]" for label, model_id in options],
        pre_selected=[
            index for index, (_, model_id) in enumerate(options)
            if model_id in set(current or ())
        ],
    )
    if current:
        selected_set = set(selected)
        selected = [index for model_id in current
                    for index, (_, option_id) in enumerate(options)
                    if option_id == model_id and index in selected_set]
        selected.extend(index for index in sorted(selected_set) if index not in selected)
    selected = _confirm_fallback_order(setup, options, selected)
    return [options[index][1] for index in selected]


def ensure_marcel_soul(agent_name: str = "Marcel") -> bool:
    """Install Marcel's default persona, never overwriting a user-customized SOUL.md."""
    from marcel_cli.config import get_marcel_home
    from marcel_cli.default_soul import DEFAULT_SOUL_MD, is_legacy_template_soul

    soul_path = get_marcel_home() / "SOUL.md"
    desired_soul = build_marcel_soul(agent_name)
    previous_named_soul = _build_previous_marcel_soul(agent_name)
    if soul_path.exists():
        try:
            existing = soul_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return False
        if existing == desired_soul:
            return False
        if (
            existing != MARCEL_SOUL_MD
            and existing != previous_named_soul
            and existing != LEGACY_MARCEL_SOUL_MD
            and existing != DEFAULT_SOUL_MD.strip()
            and not is_legacy_template_soul(existing)
        ):
            return False
    soul_path.parent.mkdir(parents=True, exist_ok=True)
    soul_path.write_text(desired_soul, encoding="utf-8")
    return True


def ensure_marcel_welcome(config: dict[str, Any], env_getter=None) -> None:
    """Write a secret-free startup card describing Marcel's live capabilities and pending setup."""
    import os
    from marcel_cli.config import get_marcel_home

    env_getter = env_getter or os.getenv
    marcel = config.get("marcel") or {}
    agent_name = str(marcel.get("agent_name") or "Marcel")
    configured = {
        label: bool(env_getter(key_env))
        for label, _provider, key_env, _base_url, _api_mode in DIRECT_PROVIDERS
    }
    accounts = (config.get("accounts") or {}).get("profiles") or []
    google_ready = any(
        isinstance(account, dict)
        and account.get("kind") == "google_workspace"
        and account.get("enabled")
        and account.get("authorization_status") == "verified"
        for account in accounts
    )
    email_ready = google_ready or any(
        isinstance(account, dict) and account.get("kind") == "imap_smtp"
        for account in accounts
    )
    tts = config.get("tts") or {}
    tts_provider = str(tts.get("provider") or "edge")
    tts_cfg = tts.get(tts_provider) if isinstance(tts.get(tts_provider), dict) else {}
    voice = (tts_cfg or {}).get("voice_id") or (tts_cfg or {}).get("voice") or "provider default"
    language = (tts_cfg or {}).get("language") or "automatic"
    image = config.get("image_gen") or {}
    video = config.get("video_gen") or {}
    web = config.get("web") or {}
    pending = []
    if not google_ready:
        pending.append("Google Workspace is not verified; offer setup only when useful.")
    if not email_ready:
        pending.append("No email account is ready; mention this once when an email task becomes relevant.")
    if not configured.get("xAI Grok"):
        pending.append("xAI is not connected.")
    if not pending:
        pending.append("No important setup item is currently pending.")
    api_lines = [
        f"- {label}: {'available' if ready else 'not configured'}"
        for label, ready in configured.items()
    ]
    content = f"""# Welcome, {agent_name}

This is your authoritative startup capability card. It contains availability only, never secret values.
Do not claim that a service is missing when it is listed as available. Use the configured tool directly.

## Available API providers
{chr(10).join(api_lines)}

## Voice
- Provider: {tts_provider}
- Voice: {voice}
- Language: {language}; follow the language used by the user.
- Voice input receives audio; text input receives text unless the user explicitly asks otherwise.

## Media and research routing
- Images: provider {image.get("provider") or "not configured"}, model {image.get("model") or "not configured"}.
- Video: provider {video.get("provider") or "not configured"}, model {video.get("model") or "provider default"}.
- Web research: backend {web.get("backend") or "automatic"}.

## Accounts
- Google Workspace: {'ready' if google_ready else 'pending'}.
- Email: {'ready' if email_ready else 'pending'}.

## Pending setup
{chr(10).join(f"- {item}" for item in pending)}

## Operating rule
Use what is already available instead of asking for another key. The configured media provider is a default,
not a restriction: choose another connected provider or model for an individual request when it better fits
quality, speed, cost, comparison, or an explicit user instruction. A retry never changes the saved default
unless the user asks to change it permanently. Surface a missing setup item briefly and only when relevant
to the user's goal; offer to complete it, but never interrupt unrelated work with setup.
"""
    (get_marcel_home() / "MARCEL_WELCOME.md").write_text(content, encoding="utf-8")


def _print_main_agent_summary(setup: Any, values: dict[str, Any], config: dict[str, Any]) -> None:
    """Show the completed main-agent choices before opening the sub-agent loop."""
    image = config.get("image_gen") if isinstance(config.get("image_gen"), dict) else {}
    setup._info(
        "Main agent configured:",
        f"- Identity: {values.get('agent_name')}",
        f"- Router/provider: {values.get('router_mode')}",
        f"- Orchestrator: {values.get('orchestrator_model') or 'automatic'}",
        f"- Fallback order: {', '.join(values.get('orchestrator_fallback_models') or ()) or 'none'}",
        f"- Main image generation/editing default: "
        f"{image.get('provider') or 'unavailable'} / {image.get('model') or 'not configured'}",
        None,
    )


def _print_subagent_summary(setup: Any, worker: dict[str, Any]) -> None:
    """Keep per-subagent summaries distinct from the main-agent summary."""
    setup._info(
        f"Sub-agent configured: {worker.get('name') or worker.get('id')}",
        f"- Activity: {worker.get('activity')}",
        f"- Model: {worker.get('model') or 'automatic'}",
        f"- Fallback order: {', '.join(worker.get('fallbacks') or ()) or 'none'}",
        f"- Capabilities: {', '.join(worker.get('toolsets') or ()) or 'none'}",
        None,
    )


def _mode_connection_defaults(
    router: dict[str, Any], current_mode: str, selected_mode: str,
) -> tuple[str, str]:
    """Return isolated URL/key-env defaults for the selected connection mode."""
    if selected_mode == "marcel_router":
        if current_mode == selected_mode:
            return (
                str(router.get("base_url") or MARCEL_ROUTER_BASE_URL),
                str(router.get("key_env") or "MARCEL_ROUTER_API_KEY"),
            )
        return MARCEL_ROUTER_BASE_URL, "MARCEL_ROUTER_API_KEY"
    if selected_mode == "custom_endpoint":
        if current_mode == selected_mode:
            return (
                str(router.get("base_url") or ""),
                str(router.get("key_env") or "MARCEL_CUSTOM_API_KEY"),
            )
        return "", "MARCEL_CUSTOM_API_KEY"
    return "", ""


def setup_marcel(config: dict) -> None:
    """Interactively configure Marcel without ever collecting secret values."""
    # Resolve through setup at call time so setup's prompt helpers remain monkeypatchable.
    from marcel_cli import setup

    existing = config.get("marcel") if isinstance(config.get("marcel"), dict) else {}
    router = existing.get("router") if isinstance(existing.get("router"), dict) else {}
    existing_delegation = config.get("delegation") if isinstance(config.get("delegation"), dict) else {}
    existing_workers = existing_delegation.get("workers")
    worker_values = []
    if isinstance(existing_workers, dict):
        worker_values = [{"id": worker_id, **worker} for worker_id, worker in existing_workers.items()
                         if isinstance(worker, dict)]
    accounts_root = config.get("accounts") if isinstance(config.get("accounts"), dict) else {}
    account_values = accounts_root.get("profiles") if isinstance(accounts_root.get("profiles"), list) else []
    setup.print_header("Marcel Agent")
    setup._info("Configure Marcel's router, orchestration workers, memory, and account metadata.",
                "Secrets are referenced by environment variable and are never written to config.yaml.", None)
    agent_name = _prompt_agent_name(setup, str(existing.get("agent_name") or ""), reconfigure=bool(existing))
    current_mode = str(router.get("mode") or "marcel_router")
    mode_index = setup.prompt_choice(
        "Connection",
        [
            "Marcel Router — one router key for every selected model",
            "Provider API keys — connect OpenAI, Gemini, Anthropic or xAI directly",
            "Custom OpenAI-compatible endpoint — one custom URL and key",
        ],
        ROUTER_MODES.index(current_mode) if current_mode in ROUTER_MODES else 0,
    )
    current_orchestrator = existing.get("orchestrator") if isinstance(existing.get("orchestrator"), dict) else {}
    current_orchestrator_model = str(current_orchestrator.get("model") or "")
    current_orchestrator_fallbacks = [
        str(model).strip() for model in current_orchestrator.get("fallback_models", [])
        if str(model).strip()
    ] if isinstance(current_orchestrator.get("fallback_models"), list) else []
    if not current_orchestrator_fallbacks:
        # Reconfiguration of older files may have only the runtime fallback key.
        from marcel_cli.fallback_config import get_fallback_chain
        provider_prefixes = {
            provider: prefix for prefix, provider in _MODEL_PROVIDER_ALIASES.items()
        }
        for entry in get_fallback_chain(config):
            model = str(entry.get("model") or "").strip()
            if not model:
                continue
            if ROUTER_MODES[mode_index] == "direct_provider":
                provider = str(entry.get("provider") or "").strip()
                prefix = provider_prefixes.get(provider)
                if prefix:
                    model = f"{prefix}/{model}"
            current_orchestrator_fallbacks.append(model)
    routing = existing.get("routing") if isinstance(existing.get("routing"), dict) else {}
    existing_live_models = (
        routing.get("model_entries")
        if current_mode == "marcel_router" and isinstance(routing.get("model_entries"), list)
        else []
    )
    values: dict[str, Any] = {
        "agent_name": agent_name,
        "router_mode": ROUTER_MODES[mode_index],
        "base_url": _mode_connection_defaults(
            router, current_mode, ROUTER_MODES[mode_index])[0],
        "api_key_ref": _mode_connection_defaults(
            router, current_mode, ROUTER_MODES[mode_index])[1],
        "direct_provider": str(
            router.get("provider") if current_mode == "direct_provider" and ROUTER_MODES[mode_index] == "direct_provider"
            else ""
        ),
        "api_mode": str(router.get("api_mode") or "chat_completions"),
        "orchestrator_model": "",
        "orchestrator_fallback_models": [],
        "available_models": [],
        "live_model_entries": list(existing_live_models),
        "workers": worker_values,
        "accounts": list(account_values),
    }
    handled_direct_providers: set[str] = set()
    live_models: list[dict[str, Any]] = list(existing_live_models)
    if values["router_mode"] == "direct_provider":
        provider = _choose_direct_provider(setup, values["direct_provider"])
        _, provider_id, key_env, base_url, api_mode = provider
        values.update(direct_provider=provider_id, api_key_ref=key_env, base_url=base_url, api_mode=api_mode)
    else:
        values["base_url"] = setup.prompt(
            "Marcel Router base URL" if values["router_mode"] == "marcel_router"
            else "Custom OpenAI-compatible base URL",
            values["base_url"],
        )
        if values["router_mode"] == "marcel_router":
            key_env = values["api_key_ref"] or "MARCEL_ROUTER_API_KEY"
            existing_router_key = setup.get_env_value(key_env)
            while True:
                if existing_router_key:
                    key_action = setup.prompt_choice(
                        "Marcel Routing account",
                        [
                            "Use my existing API key",
                            "Replace it with another API key",
                            "Open the Marcel Routing website",
                        ],
                        0,
                        description="Your existing key is stored securely and will never be displayed.",
                    )
                    if key_action == 2:
                        setup._info(
                            "Marcel Routing",
                            f"Create or manage your API keys at {MARCEL_API_KEYS_URL}",
                            None,
                        )
                        if not setup.prompt_yes_no("Continue using the existing key?", True):
                            return
                    router_key = (
                        setup.prompt("New Marcel Routing API key", password=True)
                        if key_action == 1 else existing_router_key
                    )
                else:
                    router_key = setup.prompt("Marcel Routing API key", password=True)
                if not router_key:
                    setup.print_error("No Marcel Routing API key was provided.")
                else:
                    verified, message, discovered = _discover_marcel_router_models(
                        values["base_url"], router_key)
                    if verified:
                        live_models = discovered
                        values["live_model_entries"] = discovered
                        if router_key != existing_router_key:
                            setup.save_env_value(key_env, router_key)
                        setup.print_success(message)
                        break
                    setup.print_error(message)
                if not setup.prompt_yes_no("Retry Marcel Router connection?", True):
                    return
                existing_router_key = ""
                values["base_url"] = setup.prompt(
                    "Marcel Router base URL", values["base_url"])
        else:
            try:
                values["base_url"] = _validate_custom_endpoint_url(values["base_url"])
            except ValueError as exc:
                setup.print_error(str(exc))
                return
            parsed_custom = urlsplit(values["base_url"])
            if parsed_custom.hostname and parsed_custom.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
                setup._info(
                    "Custom endpoint confirmation",
                    f"Marcel will send credentials to {values['base_url']} over HTTPS.",
                    None,
                )
                if not setup.prompt_yes_no("Continue with this custom endpoint?", False):
                    return
            values["api_key_ref"] = setup.prompt(
                "API key environment variable (never the key itself)",
                values["api_key_ref"] or "MARCEL_CUSTOM_API_KEY").replace("${", "").replace("}", "")
            custom_key = setup.prompt("Custom endpoint API key", password=True)
            if custom_key:
                setup.save_env_value(values["api_key_ref"], custom_key)
                setup.print_success("Custom endpoint connected securely.")
            elif not setup.get_env_value(values["api_key_ref"]):
                setup.print_error("No API key configured for the custom endpoint.")
                return

    # Main-agent model policy is deliberately after provider/Router validation and discovery.
    # A failed connection can therefore be retried without replaying unrelated model prompts.
    orchestrator_model = _choose_model(
        setup, "Orchestrator model", current_orchestrator_model,
        live_models=live_models,
        provider=values["direct_provider"] if values["router_mode"] == "direct_provider" else "",
    )
    orchestrator_fallbacks = _choose_fallback_models(
        setup, "general", orchestrator_model, live_models=live_models,
        current=current_orchestrator_fallbacks)
    values["orchestrator_model"] = orchestrator_model
    values["orchestrator_fallback_models"] = orchestrator_fallbacks
    values["available_models"] = _choose_available_models(
        setup, orchestrator_model, orchestrator_fallbacks, live_models=live_models)
    if values["router_mode"] == "direct_provider":
        provider_specs = {item[1]: item for item in DIRECT_PROVIDERS}
        provider = provider_specs[values["direct_provider"]]
        api_key = setup.prompt(f"{provider[0]} API key", password=True)
        if api_key:
            setup.save_env_value(provider[2], api_key)
            setup.print_success(f"{provider[0]} API key saved securely as {provider[2]}.")
        elif not setup.get_env_value(provider[2]):
            setup.print_error(f"No API key configured for {provider[0]}.")
            return
        handled_direct_providers.add(values["direct_provider"])
    if values["router_mode"] == "direct_provider":
        # Main fallback credentials are part of main-agent completion; do not defer them until
        # after specialist prompts.
        handled_direct_providers = _connect_required_direct_providers(
            setup, values, skip=handled_direct_providers)

    # A direct xAI key also enables video generation.
    if setup.get_env_value("XAI_API_KEY"):
        config.setdefault("video_gen", {}).update(
            provider="xai", model="grok-imagine-video")

    from marcel_cli.setup_tts import _setup_tts_provider
    _setup_tts_provider(config, prompt_for_voice=False)
    _choose_voice_model(setup, config, values["agent_name"])

    memory_root = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    memory = memory_root.get("maintenance") if isinstance(memory_root.get("maintenance"), dict) else {}
    values["memory_maintenance_enabled"] = setup.prompt_yes_no(
        "Enable memory maintenance?", memory.get("enabled", True) is not False)
    values["memory_maintenance_interval_hours"] = (
        _choose_memory_interval(setup, memory.get("interval_hours", 6))
        if values["memory_maintenance_enabled"] else 6
    )
    # An interval schedule is anchored when the job is created; timezone is irrelevant.
    values["timezone"] = "UTC"

    google_services_to_authorize: list[str] | None = None
    if setup.prompt_yes_no("Add Google Workspace?", False):
        selected_services = setup.prompt_checklist(
            "Choose the Google Workspace services Marcel can use",
            [label for label, _ in GOOGLE_WORKSPACE_SERVICES],
            pre_selected=[],
        )
        services = [GOOGLE_WORKSPACE_SERVICES[index][1] for index in selected_services]
        google_services_to_authorize = services
        google_client_id_env = "GOOGLE_WORKSPACE_CLIENT_ID"
        google_client_secret_env = "GOOGLE_WORKSPACE_CLIENT_SECRET"
        if setup.get_env_value(google_client_id_env):
            setup.print_success("Google OAuth Client ID is already configured.")
        else:
            google_client_id = setup.prompt("Google OAuth Client ID")
            if google_client_id:
                setup.save_env_value(google_client_id_env, google_client_id)
        if setup.get_env_value(google_client_secret_env):
            setup.print_success("Google OAuth Client Secret is already configured.")
        else:
            google_client_secret = setup.prompt("Google OAuth Client Secret", password=True)
            if google_client_secret:
                setup.save_env_value(google_client_secret_env, google_client_secret)
        values["accounts"] = [
            account for account in values["accounts"]
            if not (
                isinstance(account, dict)
                and str(account.get("type") or account.get("kind") or "").lower()
                == "google_workspace"
            )
        ]
        values["accounts"].append({
            "type": "google_workspace",
            "name": "Google Workspace",
            "services": services,
            "enabled": False,
            "authorization_status": "pending",
            "client_id_ref": "GOOGLE_WORKSPACE_CLIENT_ID",
            "client_secret_ref": "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "refresh_token_ref": "GOOGLE_WORKSPACE_REFRESH_TOKEN",
            "access_token_ref": "GOOGLE_WORKSPACE_ACCESS_TOKEN",
            "token_expiry_ref": "GOOGLE_WORKSPACE_TOKEN_EXPIRY",
            "scopes_ref": "GOOGLE_WORKSPACE_SCOPES",
        })
        setup._info(
            "Google Workspace selected. Marcel will open Google consent after saving setup;",
            "credentials and tokens remain in secret storage, never in config.yaml.",
            None,
        )

    if setup.prompt_yes_no("Add an email account?", False):
        email_provider = EMAIL_PROVIDERS[setup.prompt_choice(
            "Email provider",
            [provider[0] for provider in EMAIL_PROVIDERS],
            0,
        )]
        email_address = setup.prompt("Email address")
        imap_host, smtp_host = email_provider[1], email_provider[2]
        if not imap_host:
            imap_host = setup.prompt("Incoming mail server (IMAP)")
            smtp_host = setup.prompt("Outgoing mail server (SMTP)")
        password_env = "MARCEL_EMAIL_PASSWORD"
        password = setup.prompt("Email app password", password=True)
        if password:
            setup.save_env_value(password_env, password)
            setup.print_success(f"Email password saved securely as {password_env}.")
        credential_ready = bool(password or setup.get_env_value(password_env))
        if not credential_ready:
            setup.print_error("No email app password configured; email account was not added.")
        else:
            values["accounts"].append({
                "type": "imap_smtp",
                "name": email_address or "Email",
                "username": email_address,
                "imap_host": imap_host,
                "smtp_host": smtp_host,
                "password_ref": password_env,
                "smtp_password_ref": password_env,
            })

    telegram_requested = setup.prompt_yes_no("Connect Telegram so you can test Marcel?", True)
    if telegram_requested:
        from marcel_cli.setup_platforms import _setup_telegram
        _setup_telegram()

    # Everything owned by the main agent is complete before its summary and before specialists.
    _choose_image_provider(setup, config)
    _print_main_agent_summary(setup, values, config)
    while setup.prompt_yes_no("Add a sub-agent?", default=False):
        name = setup.prompt("Sub-agent name")
        activity_index = setup.prompt_choice("Sub-agent activity", list(ACTIVITIES), 1)
        activity = ACTIVITIES[activity_index]
        sub_agent_model = _choose_model(
            setup,
            f"Sub-agent model for {activity}",
            allow_automatic=True,
            activity=activity,
            live_models=live_models,
        )
        if activity == "image":
            setup._info(
                "Image worker context: this is a separate sub-agent route.",
                "Choose image generation/editing and image analysis (vision) capabilities independently; "
                "it does not change the main agent's image default.",
                None,
            )
        if activity == "search" and not values.get("search_provider_configured"):
            setup._info(
                "Choose how this specialist searches the web.",
                "This is separate from the AI model selected above.",
                None,
            )
            search_provider = setup.prompt_choice(
                "Web search source",
                [
                    "Brave Search — private web search (API key required)",
                    "Automatic — use the best search engine already available",
                ],
                0,
            )
            if search_provider == 0:
                brave_key = setup.prompt("Brave Search API key", password=True)
                if brave_key:
                    setup.save_env_value("BRAVE_SEARCH_API_KEY", brave_key)
                    values["web_backend"] = "brave-free"
                    setup.print_success("Brave Search connected securely.")
                elif setup.get_env_value("BRAVE_SEARCH_API_KEY"):
                    values["web_backend"] = "brave-free"
                    setup.print_success("Using the existing Brave Search connection.")
                else:
                    setup.print_error(
                        "No Brave Search API key was provided; Marcel will use automatic web search.")
            values["search_provider_configured"] = True
        fallback_models = _choose_fallback_models(
            setup, activity, sub_agent_model, live_models=live_models)
        worker = {
            "name": name,
            "activity": activity,
            "model": sub_agent_model,
            "fallbacks": fallback_models,
            "toolsets": _choose_capabilities(setup, activity),
            "concurrency": _choose_concurrency(setup, activity),
        }
        values["workers"].append(worker)
        _print_subagent_summary(setup, worker)

    if values["router_mode"] == "direct_provider":
        _connect_required_direct_providers(
            setup, values, skip=handled_direct_providers)

    try:
        apply_marcel_config(config, values)
    except ValueError as exc:
        setup.print_error(f"Marcel configuration was not saved: {exc}")
        return
    setup.save_config(config)
    continue_after_google_failure = True
    if google_services_to_authorize is not None:
        try:
            from marcel_cli.auth import login_google_workspace
            result = login_google_workspace(google_services_to_authorize)
            if result.get("verified"):
                for profile in config.get("accounts", {}).get("profiles", []):
                    if isinstance(profile, dict) and profile.get("kind") == "google_workspace":
                        profile["enabled"] = True
                        profile["authorization_status"] = "verified"
                setup.save_config(config)
                setup.print_success("Google Workspace access authorized and verified.")
            else:
                setup.print_error(
                    "Google Workspace authorization did not complete. "
                    "Your Marcel configuration was saved, but Google access is still disabled."
                )
                continue_after_google_failure = setup.prompt_yes_no(
                    "Continue to Telegram setup anyway?", False)
        except Exception as exc:
            for profile in config.get("accounts", {}).get("profiles", []):
                if isinstance(profile, dict) and profile.get("kind") == "google_workspace":
                    profile["enabled"] = False
                    profile["authorization_status"] = "pending"
            setup.save_config(config)
            setup.print_error(
                "Marcel was configured, but Google Workspace authorization did not complete: "
                f"{exc}"
            )
            continue_after_google_failure = setup.prompt_yes_no(
                "Continue to Telegram setup anyway?", False)
    try:
        ensure_marcel_soul(values["agent_name"])
        ensure_marcel_welcome(config, env_getter=setup.get_env_value)
    except OSError as exc:
        setup.print_error(f"Marcel was configured, but its startup files could not be updated: {exc}")
    try:
        ensure_memory_maintenance_job(config["memory"]["maintenance"])
    except Exception as exc:
        setup.print_error(f"Marcel was configured, but the memory schedule could not be updated: {exc}")
    if not continue_after_google_failure:
        setup.print_success(
            "Marcel configuration saved. Run 'marcel setup' when you are ready to retry Google Workspace.")
        return
    if telegram_requested:
        from marcel_cli.gateway import _is_service_running, _spawn_detached_gateway, ensure_gateway_service
        gateway_running = _is_service_running() or ensure_gateway_service(context="setup")
        if not gateway_running:
            gateway_running = _spawn_detached_gateway()
        if gateway_running:
            setup.print_success("Telegram is online. Open the bot and send /start.")
        else:
            setup.print_error(
                "Telegram was configured, but Marcel could not start its gateway automatically.")
    setup.print_success("Marcel configuration saved.")