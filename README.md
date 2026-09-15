# Marcel

Marcel is an autonomous, client-configurable agent framework for orchestrating capable AI work.
It provides memory, schedules, messaging gateways, skills, plugins, and concurrent delegation
through a business-oriented orchestration layer.

- Website: https://marcel-agent.com
- Marcel Routing: https://marcel-agent.com/routing
- Documentation: https://marcel-agent.com/docs
- Dashboard: https://marcel-agent.com/dashboard
- Billing: https://marcel-agent.com/billing
- API keys: https://marcel-agent.com/api-keys
- Usage: https://marcel-agent.com/usage

## Install

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/AdMind-ai/marcel-agent/main/scripts/install.sh \
  -o /tmp/marcel-install.sh
bash /tmp/marcel-install.sh
```

Windows PowerShell:

```powershell
Invoke-WebRequest `
  https://raw.githubusercontent.com/AdMind-ai/marcel-agent/main/scripts/install.ps1 `
  -OutFile marcel-install.ps1
.\marcel-install.ps1
```

For a versioned installer and checksummed source archive, use the
[GitHub Releases](https://github.com/AdMind-ai/marcel-agent/releases) page.

## Why Marcel exists

Marcel builds on its documented upstream foundation while adding a
business-oriented control and deployment layer.

| Area | Upstream foundation | Marcel |
| --- | --- | --- |
| Orchestration | Base delegation | Configurable orchestrator and worker registry |
| Routing | Provider/model selection | Deterministic `cheapest_capable` policy |
| Business controls | Limited | Budgets, usage metadata, billing and policy hooks |
| Deployment | Personal agent runtime | Dedicated single-tenant personal or business deployment |
| Integrations | General-purpose integrations | Customer account profiles and guided setup |
| UX | General agent experience | Business-first setup, quiet defaults and non-interrupting steering |

Marcel's original work and modifications are Apache-2.0 licensed. Upstream
provenance and its MIT notices are documented in [UPSTREAM.md](UPSTREAM.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Current foundation

- OpenAI-compatible Marcel Router contract and offline validator covering chat,
  model discovery, image generation, realtime voice, asynchronous video,
  embeddings, moderation, reranking, translation, document translation, and
  search/data tools. This source tree does not establish availability of a
  hosted router.
- Configurable orchestrator plus an unbounded registry of named workers.
- Worker-specific provider, model, tools/toolsets, concurrency, iteration, timeout, fallback, and
  budget metadata.
- Deterministic `cheapest_capable` routing configuration.
- BYOK support for customer-owned OpenAI-compatible endpoints.
- Google Workspace OAuth metadata and generic IMAP/SMTP account profiles.
- Secret references only: API keys, passwords, refresh tokens, and client secrets are not written
  into YAML.
- Durable memory-maintenance schedule, enabled every six hours by default.
- Quiet defaults: tool progress off and STT transcript echo disabled.

## Router contract

The router contract is documented in:

- [docs/marcel-router.md](docs/marcel-router.md)
- [docs/marcel-router-openapi.yaml](docs/marcel-router-openapi.yaml)

Documented router endpoints (deployment availability must be verified):

```text
Base URL                       <deployment>/api
GET    /v1/models              Model catalog
POST   /v1/chat/completions    Chat completions and streaming
POST   /v1/images/generations  Text-to-image generation
POST   /v1/realtime/sessions   One-use realtime voice session token
GET    /v1/realtime/connect    OpenAI Realtime/Gemini Live WebSocket
POST   /v1/videos              Asynchronous Sora/Veo video generation
GET/DELETE /v1/videos/{id}     Video status and deletion
GET    /v1/videos/{id}/content Completed video content
POST   /v1/embeddings          Embeddings
POST   /v1/moderations         Content moderation
POST   /v1/rerank              Document reranking
POST   /v1/translate           Text translation
POST   /v1/documents/translations
                               Asynchronous document translation
GET    /v1/tools               Tool catalog
POST   /v1/tools/search        Search/data tool execution
```

Marcel normally chooses a concrete namespaced model such as `provider/model` before calling the
router. The router does not silently replace the selected model.

## Development setup

```bash
cd marcel-agent
uv sync
uv run marcel setup marcel
uv run marcel
```

## Configuration shape

The Marcel wizard writes to native runtime sections:

- `marcel` — brand, router mode, orchestrator, and routing policy.
- `providers` and `model` — active OpenAI-compatible endpoint and orchestrator model.
- `delegation.workers` — named worker registry.
- `accounts.profiles` — Google Workspace or IMAP/SMTP metadata.
- `memory.maintenance` — six-hour maintenance policy and cron job name.

Example:

```yaml
marcel:
  agent_name: Marcel
  router:
    mode: byok
    base_url: https://marcel-agent.com/api/v1
    key_env: CUSTOMER_MODEL_API_KEY
  orchestrator:
    provider: marcel-byok
    model: openai/gpt-5
  routing:
    strategy: cheapest_capable

delegation:
  workers:
    research:
      activity: search
      provider: marcel-byok
      model: google/gemini-flash
      toolsets: [web, documents]
      max_concurrency: 4
      fallback_models: [openai/gpt-5-mini]
      budget:
        max_requests: 100
```

Actual secret values belong in environment variables or the deployment secret manager. YAML stores
only references such as `${CUSTOMER_MODEL_API_KEY}`.

## Worker dispatch

Models can dispatch a configured worker through `delegate_task(worker="research", ...)`. Resolution
precedence is:

```text
delegation defaults < named worker < trusted call overrides
```

Worker registries have no fixed size limit. Runtime execution remains bounded by configured
concurrency, provider quotas, available resources, and budgets.

## Test the router

Run the complete compatibility suite offline:

```bash
uv run marcel-router-validate \
  --fixture tests/fixtures/marcel_router_validator.json
```

When a real router is available, live validation can be run:

```bash
export MARCEL_ROUTER_API_KEY="..."
export MARCEL_ROUTER_BASE_URL="https://<deployment>/api/v1"
uv run marcel-router-validate --base-url "$MARCEL_ROUTER_BASE_URL"
```

For CI or machine-readable diagnostics, add `--json`. Offline fixture status is
covered by the test suite; live endpoint validation has not been run from this
source tree. The validator checks health, catalog metadata, normal chat, SSE
streaming, tool calls, structured JSON, authentication errors, invalid-model
errors, and advertised extended capabilities. Realtime WebSocket event exchange
requires a live endpoint and is reported as a live-only validation gap. The API
key is read from the environment and is never written to a fixture or report.

Deterministic routing fixtures are available in `tests/fixtures/marcel_routing_config.json` and
`tests/fixtures/marcel_router_catalog.json`.

## Defaults introduced by Marcel

```yaml
display:
  tool_progress: "off"

stt:
  echo_transcripts: false

memory:
  maintenance:
    enabled: true
    interval_hours: 6
    timezone: UTC
    run_only_when_changed: true
```

The setup wizard creates or updates a persistent cron job named
`marcel-memory-maintenance`. It can also disable the job.

## Naming and mascot

Marcel's visual identity uses an original monkey mascot. Do not copy costumes, props, poses, or
other protected visual elements associated with the character Marcel from *Friends*.

## License

Copyright 2026 Admind Srl.

New Marcel work and modifications are licensed under the
[Apache License 2.0](LICENSE). Marcel includes portions derived from
MIT-licensed upstream software; the required upstream copyright and license
notices are preserved in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
See [UPSTREAM.md](UPSTREAM.md) for provenance details.