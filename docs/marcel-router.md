# Marcel Router contract

## Scope and compatibility

Marcel Router exposes an OpenAI-compatible API at `/api`. The normative wire
contract is [`marcel-router-openapi.yaml`](marcel-router-openapi.yaml), OpenAPI
3.1. The router is a contract and client-routing layer; it does not require
changes to the imported Marcel runtime.

Hosted Router availability is deployment-specific and is not established by
this source tree. When a deployment is available, its API base is
`<deployment>/api/v1`. Account management, API keys, usage, and billing may be
provided by that deployment at:

- Routing: https://marcel-agent.com/routing
- Dashboard: https://marcel-agent.com/dashboard
- API keys: https://marcel-agent.com/api-keys
- Usage: https://marcel-agent.com/usage
- Billing: https://marcel-agent.com/billing

The documented contract includes `GET /healthz`, the public `GET /catalog`,
model discovery, chat completions, image generation, realtime voice sessions
and WebSockets, asynchronous video jobs, embeddings, moderation, reranking,
text and document translation, and search/data tools. Account, billing, usage,
and managed-agent operations are also described under `/portal`. Health,
catalog, and portal authentication behavior follows the OpenAPI document;
authenticated model and `/v1` operations require the authorization described
below. Offline fixture validation covers HTTP behavior; live endpoint and
realtime WebSocket availability must be checked separately.

## Authentication and BYOK

Clients send `Authorization: Bearer <Marcel API key>` to the router. Missing or
invalid credentials return `401` with `{ "error": { "message", "type", ... } }`.
Provider credentials are not sent as a replacement for the Marcel bearer token.

```python
from openai import OpenAI

client = OpenAI(
    api_key="LA_TUA_API_KEY_MARCEL",
    base_url="https://marcel-agent.com/api/v1",
)
```

```bash
curl https://marcel-agent.com/api/v1/chat/completions \
  -H "Authorization: Bearer LA_TUA_API_KEY_MARCEL" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MODEL_ID",
    "messages": [{"role": "user", "content": "Ciao"}]
  }'
```

Bring-your-own-key (BYOK) is compatible with this contract: a Marcel
installation may resolve provider credentials from its configured secure
credential store for the authenticated principal. It must not expose those
credentials in model listings, responses, job records, error messages, or
client-visible routing metadata. A provider that is unavailable to the
principal, including because its BYOK credential is absent, is omitted from
`/v1/models`; an explicit request for it fails with a typed error rather than
silently falling back to another provider.

## Models and deterministic routing

Every model identifier is namespaced: `provider/model`, for example
`openai/gpt-4o-mini`. The slash is required. Unnamespaced aliases are not part
of the contract. `GET /v1/models` returns only models usable by the caller and adds
a canonical `metadata` object containing the model capabilities, routing
recommendations, cost/speed/quality tiers, and context window. The metadata
also explicitly advertises `supports_streaming`, `supports_tool_calls`, and
`supports_json_schema` booleans.

Routing is deterministic and performed by the client: it selects one listed
namespaced ID based only on locally available inputs (requested capability,
policy, cost/latency preferences, and the stable model metadata), then sends
that exact ID. The router dispatches to that namespace's provider and does not
perform hidden retries, cross-provider fallback, or model substitution. This
makes routing auditable and keeps the same client inputs and model catalogue
decision reproducible. Clients should record the selected ID and catalogue
version/snapshot when reproducibility matters.

## Chat, tools, structured output, and streaming

`/v1/chat/completions` accepts OpenAI message arrays, sampling options, OpenAI
function tools, `tool_choice`, and `response_format` (`text`, `json_object`, or
`json_schema`). Tool arguments are JSON encoded in
`message.tool_calls[].function.arguments`; a client executes them and submits a
subsequent `tool` message with the matching `tool_call_id`. Capability support
is advertised in `model.metadata.capabilities`, while streaming, tool calls,
and structured output are governed by their corresponding
`model.metadata.supports_streaming`, `model.metadata.supports_tool_calls`, and
`model.metadata.supports_json_schema` booleans. Asking an unsupported model for
a feature is a `400`, not a degraded response.

With `stream: false` the endpoint returns one `chat.completion` with `usage`
(`prompt_tokens`, `completion_tokens`, and `total_tokens`). With `stream: true`
it returns SSE. Each event is `data: <JSON ChatCompletionChunk>` and completion
is `data: [DONE]`; tool-call deltas can be split and are joined by `index`.
When `stream_options.include_usage` is true, the terminal chunk includes usage.

## Media and realtime voice

`POST /v1/images/generations` provides OpenAI-compatible text-to-image
generation. It accepts text prompts and returns generated image data; image
inputs belong to chat vision support rather than this operation.

Realtime voice uses an explicit two-step flow. Call
`POST /v1/realtime/sessions` with recording and audio-processing consent to
receive a one-use token, then upgrade `GET /v1/realtime/connect` to a
WebSocket using the `marcel-realtime` subprotocol and token. The WebSocket
relays OpenAI Realtime or Gemini Live client/provider events, including
interruption events. Tokens expire after 60 seconds and sessions have provider
spending, duration, message, and audio limits documented in the OpenAPI
contract. Never put the token in a URL.

Video generation is asynchronous: `POST /v1/videos` starts a Sora or Veo job
and returns its video record. Use `GET /v1/videos/{id}` to inspect and refresh
status, `DELETE /v1/videos/{id}` to remove the job and retained media, and
`GET /v1/videos/{id}/content` to download completed video content. Job metadata
and generated media expire according to the retention policy in the contract.

## Embeddings, safety, translation, and tools

The router also exposes OpenAI-compatible `POST /v1/embeddings`, text
moderation through `POST /v1/moderations`, document reranking through
`POST /v1/rerank`, and formatting-preserving text translation through
`POST /v1/translate`. Layout-preserving PDF, DOCX, and PPTX translation is
submitted with `POST /v1/documents/translations`; retrieve status with
`GET /v1/documents/translations/{id}` and download the completed document with
`GET /v1/documents/translations/{id}/content`.

`GET /v1/tools` lists available search and data tools, and
`POST /v1/tools/search` runs a normalized tool request. These router tools are
distinct from Marcel agent plugins and their media behavior; agent plugins
continue to use their existing interfaces.

## Errors and versioning

All non-success API errors use
`{ "error": { "message": "...", "type": "...", "param": null, "code": null } }`.
`400`, `401`, `404`, `429`, and `500` have their conventional meanings; callers
must not infer a fallback provider from any error.

The API version is the `/v1` path major version. Additive fields, optional
metadata, models, and capabilities may be introduced within v1; clients must
ignore fields they do not understand. Removing or changing a required field,
altering endpoint semantics, or changing deterministic-routing rules requires a
new path major version. `/health.version` reports the deployed contract version.