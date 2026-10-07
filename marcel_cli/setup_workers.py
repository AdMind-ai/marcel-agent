"""Worker setup screens and validated, credential-free template import."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tools.delegate_worker_registry import WorkerConfigError, parse_workers


def import_worker_template(path: str, existing: list[dict]) -> list[dict]:
    """Read a YAML/JSON mapping or list; reject the whole import on any error."""
    source = Path(path).expanduser()
    if source.stat().st_size > 256 * 1024:
        raise WorkerConfigError("Worker template exceeds 256 KiB")
    try:
        text = source.read_text(encoding="utf-8")
        if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)):
            raise WorkerConfigError("Worker template aliases are not supported")

        class TemplateLoader(yaml.SafeLoader):
            pass

        def unique_mapping(loader, node):
            result = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node)
                if not isinstance(key, str) or key in result:
                    raise WorkerConfigError("Worker template has invalid or duplicate keys")
                result[key] = loader.construct_object(value_node)
            return result

        TemplateLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
        raw = yaml.load(text, Loader=TemplateLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        # Parser errors include source lines, possibly credentials. Never echo them.
        raise WorkerConfigError("Worker template is not valid YAML/JSON") from exc
    workers = parse_workers(raw)
    if not workers:
        raise WorkerConfigError("Worker template contains no workers")
    from marcel_cli.setup_marcel import ACTIVITIES, normalize_worker
    existing_ids = {normalize_worker(worker)["id"] for worker in existing}
    for worker_id, worker in workers.items():
        normalized_id = normalize_worker(worker)["id"]
        if normalized_id in existing_ids:
            raise WorkerConfigError("Worker template conflicts with an existing worker")
        existing_ids.add(normalized_id)
        if worker.get("activity", "general") not in ACTIVITIES:
            raise WorkerConfigError("Worker template has an unknown activity")
        if not worker.get("model"):
            raise WorkerConfigError("Worker template requires an explicit chat model")
        from toolsets import TOOLSETS
        if any(name not in TOOLSETS for name in worker.get("toolsets", [])):
            raise WorkerConfigError("Worker template has an unknown toolset")
        if worker.get("tools"):
            from tools.registry import registry, discover_builtin_tools
            discover_builtin_tools()
            if any(name not in registry.get_all_tool_names() for name in worker["tools"]):
                raise WorkerConfigError("Worker template has an unknown tool")
    from marcel_cli.setup_model_labels import LIVE_SETUP_CATALOG, validate_worker_models
    validate_worker_models(list(workers.values()), LIVE_SETUP_CATALOG.get())
    return list(workers.values())


def choose_worker_limits(setup: Any) -> dict:
    """Budgets are per run, never applied to the main agent."""
    setup._info(
        "Sub-agent permissions and limits",
        "These settings affect only this worker. Main-agent autonomy is unchanged.",
        "Selected tools excludes automatic MCP inheritance and task-level additions.",
        None,
    )
    permission = setup.prompt_choice(
        "Sub-agent permissions",
        ["Only the selected tools", "Inherit the main agent's tools"],
        0,
    )
    limits: dict = {"permissions": "selected" if permission == 0 else "inherit"}
    while True:
        try:
            raw = setup.prompt("Maximum API requests per worker run (blank = no limit)", "")
            budget = {"max_requests": raw} if raw.strip() else {}
            duration = setup.prompt("Maximum worker duration in seconds (blank = no limit)", "")
            if duration.strip():
                budget["max_duration_seconds"] = duration
            if setup.prompt_yes_no("Set token or estimated cost limits for this worker?", False):
                setup._info(
                    "Token and cost limits use reported usage.",
                    "An in-flight response can exceed these thresholds; no further request is sent afterwards.",
                    "Requests include retries; auxiliary provider operations are not prepaid billing caps.",
                    None,
                )
                for field, label in (
                    ("max_input_tokens", "Maximum input tokens"),
                    ("max_output_tokens", "Maximum output tokens"),
                    ("max_total_tokens", "Maximum total tokens"),
                    ("max_cost_usd", "Maximum estimated cost in USD"),
                ):
                    raw = setup.prompt(f"{label} per worker run (blank = no limit)", "")
                    if raw.strip():
                        budget[field] = raw
            if budget:
                limits["budget"] = budget
            validated = parse_workers({"worker": {**limits, "toolsets": ["file"]}})["worker"]
            validated.pop("toolsets")
            validated.pop("id")
            return validated
        except WorkerConfigError as exc:
            limits.pop("budget", None)
            setup.print_error(str(exc))


def print_worker_summary(setup: Any, worker: dict) -> None:
    from tools.delegate_worker_registry import _BUDGET_FIELDS
    budget = {field: worker[field] for field in _BUDGET_FIELDS if field in worker}
    budget.update(worker.get("budget") or {})
    setup._info(
        f"Sub-agent configured: {worker.get('name') or worker.get('id')}",
        f"- Activity: {worker.get('activity', 'general')}",
        f"- Model: {worker.get('model') or 'automatic'}",
        f"- Fallback order: {', '.join(worker.get('fallbacks') or worker.get('fallback_models') or []) or 'none'}",
        f"- Concurrency: {worker.get('max_concurrency') or worker.get('concurrency') or 'global limit'}",
        f"- Permissions: {worker.get('permissions', 'inherit')}",
        f"- Tools: {', '.join(worker.get('tools') or worker.get('toolsets') or []) or 'inherited'}",
        f"- Budget per run: {', '.join(f'{key}={value}' for key, value in budget.items()) or 'no individual limit'}",
        f"- Iterations: {worker.get('max_iterations', 'global limit')}; "
        f"timeout: {worker.get('timeout_seconds', 'global setting')}",
        None,
    )
    from marcel_cli.setup_model_labels import LIVE_SETUP_CATALOG, model_label
    for model in [worker.get("model")] + list(worker.get("fallbacks") or worker.get("fallback_models") or []):
        entry = next((entry for entry in LIVE_SETUP_CATALOG.get() or [] if isinstance(entry, dict) and entry.get("id") == model), None)
        if entry:
            setup._info(model_label(entry), None)


def configure_workers(setup: Any, values: dict, *, live_models: list | None = None) -> None:
    from marcel_cli.setup_marcel import (
        ACTIVITIES, ACTIVITY_LABELS, _choose_model, _choose_fallback_models, _choose_capabilities,
        _choose_concurrency, normalize_worker,
    )
    while setup.prompt_yes_no("Add a sub-agent?", default=False):
        mode = setup.prompt_choice(
            "Sub-agent configuration", ["Configure manually", "Import YAML/JSON worker template"], 0,
        )
        if mode == 1:
            try:
                imported = import_worker_template(
                    setup.prompt("Worker template path"), values["workers"],
                )
                for worker in imported:
                    print_worker_summary(setup, worker)
                if setup.prompt_yes_no("Import these workers?", True):
                    values["workers"].extend(imported)
            except (OSError, ValueError):
                setup.print_error("Worker template rejected. Check its schema, IDs, tools and limits; nothing was imported.")
            continue
        worker = {"name": setup.prompt("Sub-agent name")}
        worker["activity"] = ACTIVITIES[setup.prompt_choice("Sub-agent activity", list(ACTIVITY_LABELS), 1)]
        provider = values.get("direct_provider", "") if values.get("router_mode") == "direct_provider" else ""
        try:
            worker["model"] = _choose_model(
                setup, f"Sub-agent model for {worker['activity']}",
                activity=worker["activity"],
                live_models=live_models, provider=provider,
            )
        except ValueError as exc:
            setup.print_error(str(exc))
            continue
        if not worker["model"]:
            setup.print_error("This worker requires an explicit compatible chat/tool model.")
            continue
        worker["fallbacks"] = _choose_fallback_models(
            setup, worker["activity"], worker["model"],
            live_models=live_models, provider=provider,
        )
        if worker["activity"] == "search" and not values.get("search_provider_configured"):
            setup._info(
                "Choose how this specialist searches the web.",
                "This is separate from the AI model selected above.",
                None,
            )
            search_provider = setup.prompt_choice(
                "Web search source",
                ["Brave Search — private web search (API key required)",
                 "Automatic — use the best search engine already available"],
                0,
            )
            if search_provider == 0:
                brave_key = setup.prompt("Brave Search API key", password=True)
                if brave_key:
                    setup.save_env_value("BRAVE_SEARCH_API_KEY", brave_key)
                    values["web_backend"] = "brave-free"
                elif setup.get_env_value("BRAVE_SEARCH_API_KEY"):
                    values["web_backend"] = "brave-free"
                else:
                    setup.print_error("No Brave Search key configured; using automatic search.")
            values["search_provider_configured"] = True
        worker["toolsets"] = _choose_capabilities(setup, worker["activity"])
        limits = choose_worker_limits(setup)
        worker.update(limits)
        if worker["permissions"] == "inherit":
            worker.pop("toolsets", None)
        worker["concurrency"] = _choose_concurrency(setup, worker["activity"])
        try:
            normalized = normalize_worker(worker)
            if normalized["id"] in {normalize_worker(w)["id"] for w in values["workers"]}:
                raise WorkerConfigError("Worker name already exists")
            from marcel_cli.setup_model_labels import LIVE_SETUP_CATALOG, validate_worker_models
            validate_worker_models([normalized], LIVE_SETUP_CATALOG.get())
            print_worker_summary(setup, worker)
            values["workers"].append(worker)
        except ValueError as exc:
            setup.print_error(str(exc))
