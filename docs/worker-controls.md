# Worker setup controls

The setup wizard shows the main-agent summary before asking for workers.
Worker permissions, budgets and concurrency never change the main agent's
approval policy. Existing main approval settings are preserved.

For each worker, choose its name, activity, chat model, ordered fallbacks,
tools, permissions, resource limits and concurrency. Image/video workers
use a **chat/tool model** to call the separately configured media service;
a generation backend is not a worker LLM.

## Permissions

- `selected`: only the chosen toolsets/tools, intersected with the tools the
  parent actually has. Automatic MCP inheritance and implicit recursive
  delegation are disabled. A retained execution allowlist remains effective
  after a schema refresh.
- `inherit`: inherit the parent's tools, subject to the runtime's normal
  blocked child tools and depth rules.

These are capability permissions, not an operating-system sandbox. Giving a
worker a terminal or arbitrary code execution grants those tools' abilities;
it is not equivalent to read-only filesystem access. Dangerous-command
approvals continue to follow the existing installation policy.

## Budgets

Limits apply to **each worker run**, not to all runs combined:

- `max_requests`: counts main-model attempts, including retries and
  structured-output repair. No further attempt is dispatched at the limit.
- `max_duration_seconds` / `timeout_seconds`: use the earlier applicable
  deadline. A timed-out thread retains its concurrency slot until it exits.
- `max_input_tokens`, `max_output_tokens`, `max_total_tokens`,
  `max_cost_usd`: stop further main-model requests at the reported usage
  threshold. Output caps are narrowed to remaining output-token allowance.
  One in-flight response can cross a threshold; these are **not prepaid
  billing caps**. Missing usage/cost information stops subsequent requests
  explicitly instead of treating missing data as zero.

Auxiliary calls (such as compression), tool-provider charges and external
services are not included in the main-model request count. Use the provider's
own account limits for a hard billing ceiling. Budgeted workers on external
agent transports that bypass the local model loop are rejected rather than
silently running without limits.

`max_concurrency` is shared by runs of the same named worker under one parent,
including separate dispatches. The global delegation concurrency ceiling also
applies. Excess concurrent runs receive an explicit capacity error.

## Import a worker template

Choose **Import YAML/JSON worker template**. Templates may contain a mapping
keyed by worker ID or a list with an `id` in every entry. Review the displayed
worker summaries and confirm before importing:

```yaml
reviewer:
  activity: coding
  model: provider/chat-model
  fallback_models:
    - provider/backup-model
  toolsets: [file]
  permissions: selected
  max_concurrency: 2
  max_iterations: 20
  budget:
    max_requests: 8
    max_duration_seconds: 180
```

The entire import is rejected on invalid fields, limits, IDs, duplicate keys,
unknown tools/toolsets, credentials, recursive/alias YAML or conflicting IDs.
Files are limited to 256 KiB. With a live Router catalog, both primary and
fallback models must be available chat/tool-capable entries. Direct/custom
endpoints allow operator-supplied IDs; known media-only backends are rejected.
Credentials belong to the installation's secure storage, never to a template.

Live model choices show the selected ID, canonical ID, provider, capabilities,
Router availability, alias status and preview status. Unavailable/direct-only
entries are not offered as Router worker models. Offline recommendations are
marked as unverified rather than claiming account availability.
