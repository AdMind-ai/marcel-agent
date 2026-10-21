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

- `max_requests`: counts main-model attempts, auxiliary-model attempts (including
  compression, vision and MoA advisors/aggregators), and service-tool operations.
  Retries and structured-output repair count too. No further operation is
  dispatched at the limit.
- `max_duration_seconds` / `timeout_seconds`: use the earlier applicable
  deadline. A timed-out thread retains its concurrency slot until it exits.
- `max_input_tokens`, `max_output_tokens`, `max_total_tokens`,
  `max_cost_usd`: stop further model and tool operations at the reported usage
  threshold. Output caps are narrowed to remaining output-token allowance.
  One in-flight response can cross a threshold; these are **not prepaid
  billing caps**. Missing usage/cost information stops subsequent requests
  explicitly instead of treating missing data as zero.

Each run has an independent, thread-safe ledger, propagated to auxiliary and
tool threads. Session totals and the main agent's costs are never used as its
budget authority. Provider-reported tool costs and auxiliary-model usage/pricing
are included. A provider price is preferred over a model-price estimate.
Services without measurable cost are listed in the delegation result's
`budget_usage.unmeasurable_operations`; with a cost ceiling, they prevent any
subsequent operation. Non-token services do not pretend to report LLM tokens.
Provider tools can return `usage` plus `cost_usd`/`cost` (USD) or
`estimated_cost_usd`/`cost_status`. Built-in provider adapters record these
fields before reducing their output. Unknown plugin toolsets reserve a service
operation conservatively; known local and auxiliary-only toolsets do not
double-count file operations or vision's auxiliary LLM request.

Concurrent operations reserve request slots atomically. Operations already
admitted may finish after a token/cost threshold is reached; later operations
are blocked. These limits cannot cancel provider invoices or guarantee a
prepaid ceiling. Local file/terminal tools are not billed requests, but their
execution is blocked once the run budget is exhausted. Arbitrary code or shell
commands can call external services without exposing their billing metadata;
these are not a billing sandbox. Use selected permissions and the provider's
own account limits for a hard billing ceiling.

### External agents (ACP / Codex app-server)

External workers support request and duration budgets. Here `max_requests`
counts admitted **ACP prompts / Codex turns**, plus any separately observable
Marcel operations, not the model calls or tools hidden inside the external
agent. Initialization and protocol messages do not count as model requests.
The last admitted turn can finish; the next dispatch is refused.

The duration deadline includes handshake and execution. Marcel requests
`session/cancel` / `turn/interrupt` and terminates the subprocess if necessary,
including peers that ignore cancellation. Cancellation cannot undo billed work.

Token thresholds require provider-reported consumption: ACP prompt-response
input/output usage, or Codex cumulative thread totals (not `last`, which covers
only the last internal model call). Missing, malformed or decreasing cumulative
usage stops the worker explicitly rather than reusing stale session totals.
ACP can only report at the end of a prompt; Codex can trigger cancellation on
usage notifications. These are reported-consumption thresholds, not remote
generation caps; an in-flight internal call can exceed them.

`max_cost_usd` is refused before dispatch on these transports because neither
wire provides reliable USD billing for the external agent's whole operation.
Subscription access is not treated as zero-cost, and Marcel model price
estimates do not substitute for unknown external billing.

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
