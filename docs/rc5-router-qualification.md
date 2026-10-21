# Router qualification: v0.21.0-rc.5

## Publication and scope

The user explicitly approved the correction and publication of rc.5 after the
rc.4 normal-install pilot failed. This is a prerelease, not a stable release.
No stable publication has been authorized.

**Current outcome, 2026-10-08: required normal-flow Router pilot PASSED.**
Normal installation, main inference, both fallback models, configuration reload
and real execution of the specifically registered image worker passed live.
This qualifies only the tested Router path, not general product stability or a
stable release. Actual image generation, automatic failover during an outage,
Windows installation and the full-screen curses UI remain untested.

### Authorization history

The user declined the proposed additional Ubuntu run and explicitly requested:
“No, lascia le verifiche sospese e rc.5 non qualificata.”

That campaign stopped with an **unqualified** outcome, not a successful
completion of the original live qualification. On 2026-10-08 the user explicitly
authorized resuming **only the live checks**. No additional release or stable
promotion is authorized. Qualification-driver changes remain separate from the
immutable product tag and release assets.

- Release: https://github.com/AdMind-ai/marcel-agent/releases/tag/v0.21.0-rc.5
- Product commit: `75df0f68aa40bee56b295596bc4bc1df8651f514`
- Public branch: `release/v0.21.0-rc.5`
- Live pilot: https://github.com/AdMind-ai/marcel-agent/actions/runs/37667034224
- Qualification-driver commit: `a592023d` (separate from the product tag)

The candidate includes the integrated public rc.4 baseline and worker controls.
The normal Bash and PowerShell installers now use the canonical Marcel CLI
entrypoint. Module execution is also recognized as Marcel setup. Marcel full
setup does not launch a second legacy provider picker after saving the Router.

The release source and installers are immutable. Qualification-driver fixes,
if needed, belong on the separate qualification branch; they must not patch
the installed product.

## Simulated checks

**150 passed.** The focused suite covers setup, Router configuration and
validation, worker registry/budgets and the new product-entrypoint regressions.
It exercises both new installations and existing configurations, including
module invocation. These tests use replaced prompts/network behavior and are
not evidence of successful live inference.

Bash syntax, archive-profile boundaries and whitespace checks passed.
PowerShell's canonical invocation has a source-level regression check; this
does not claim a live Windows installation.

## Earlier campaign (before renewed authorization)

**Historical outcome: the live normal-install path had not been qualified.**

The earlier live run failed with a terminal-driver timeout while `uv` was still
preparing/installing dependencies. It did not reach the wizard. Its successful
anonymous checksums and real authenticated catalog discovery do not establish
installed main inference, worker execution or configuration reload.

No further full Ubuntu run was started before the renewed authorization. A bounded PTY search
window and disabled `uv` progress animation were prepared locally to address
driver overhead from continuously redrawn package progress. That is a test-driver
mitigation, not a proven diagnosis or a passing live result. The product's rc.5
tag and published assets remain unchanged.

The Ubuntu 24.04 job downloads every actual published asset anonymously,
verifies the downloaded SHA256SUMS, launches the normal installer under a PTY
without skip/non-interactive flags, and verifies the installed tag's commit.
It uses the user-supplied Router test credential in a dedicated, branch-restricted
temporary GitHub environment. Neither source nor public assets contain that key.

The checks require:

- the test account's authenticated model catalog;
- a main configured with no workers and a real Router response;
- two fallbacks explicitly selected and reordered in the normal UI;
- the same ordering in saved and installed-runtime-reloaded configuration;
- a subsequently configured image worker with a chat/tool-capable Router LLM,
  selected-tool permissions and request/duration budgets;
- a real main-to-worker delegation, confirmed from the disposable runtime's
  actual tool-call/result records, not solely from a quoted response marker.

The pilot uses a real PTY and the product's native numbered terminal fallback
(`TERM=marcel-qualification-numbered`, deliberately absent from terminfo).
No product functions, network client or Router response are replaced.
This does **not** validate the full-screen curses renderer.

The first rc.5 run connected to the real Router but stalled in its model picker
under `TERM=dumb` after masked credential entry. A local terminal-only
reproduction confirmed that limitation. A subsequent incomplete-driver run was
cancelled rather than counted as evidence. The driver was corrected separately
to preserve prompt context, select both fallbacks and keep the main order on
worker reconfiguration. A simulated protocol check passed; it is not part of
the live evidence.

A separate direct live API probe of `openai/gpt-4.1-nano` returned HTTP 200,
the exact requested response marker and usage metadata. This proves account
execution at the endpoint, not installed-runtime qualification.

An image worker's chat LLM is not its image-generation service. The pilot does
not substitute a maintainer image-provider key and does not fake a generated
image. Without a separately authorized image-service credential, actual image
generation remains untested and must be reported as such.

Only allowlisted JSON evidence may be retained. HOME, `.env`, YAML, runtime
databases and transcripts remain disposable; the remote credential/environment
must be removed after the run.

Cleanup is complete for the failed campaign: the GitHub environment and Router
secret copy have been deleted, the disposable installation HOME was removed,
and only the allowlisted failure evidence was retained. The user-supplied
workspace secret remains in Replit's secure storage for an authorized retry.

The pending driver mitigation passed a local simulated 6 MiB terminal-output
test in 0.21 seconds. `uv --help` confirms that `UV_NO_PROGRESS=1` only suppresses
progress output. Neither result proves that the clean Ubuntu installation now
completes; no new full run has been started.

## Authorized Ubuntu retry, 2026-10-08

Run: https://github.com/AdMind-ai/marcel-agent/actions/runs/37793754273

The bounded PTY / `UV_NO_PROGRESS=1` mitigation was exercised live against the
unchanged public rc.5 assets. The normal installation reached and completed
the wizard on clean Ubuntu 24.04, without skip or noninteractive flags.

Allowlisted evidence confirmed:

- Anonymous public-asset checksums passed.
- The authenticated test account catalog contained 57 models.
- Installed commit: `75df0f68aa40bee56b295596bc4bc1df8651f514`.
- Main setup completed with no workers; installed-runtime configuration reload
  and a real main response passed.
- Both selected fallback models produced real installed-runtime responses.
- The main fallback order was saved and reloaded as `openai/gpt-4o-mini`,
  then `openai/gpt-4.1-mini`.

The run failed **in the qualification driver**, after worker setup, because it
read the wizard-facing `fallbacks` field rather than the runtime's canonical
`fallback_models`. That result does not establish worker reload or delegation.
The driver correction changes neither product code nor release assets.

The subsequent retry is:
https://github.com/AdMind-ai/marcel-agent/actions/runs/37794311860

Worker configuration reload passed in that retry, but the registered-worker
completion assertion failed. A metadata-only diagnostic retry followed:
https://github.com/AdMind-ai/marcel-agent/actions/runs/37795142370

The diagnostic run's old detector reported one `delegate_task` call as selecting
the named worker, but it then accepted both top-level and unsupported nested
worker selectors. That historical flag therefore does not establish that the
runtime applied the named profile. No successful worker result was confirmed
under its then-synchronous check. A response containing the requested marker is
not proof of worker execution.

The product supports asynchronous delegation: the immediate tool result can
be a dispatch handle, while completion is stored separately in the runtime's
durable ledger. The driver was extended to check that ledger, correlated by
delegation ID and originating session, and require a completed result with
positive API consumption and the expected worker model. Seven local
result-validation cases passed; these are **simulated**, not live evidence.

The last failed retry before the next authorization was:
https://github.com/AdMind-ai/marcel-agent/actions/runs/37795912419

**Failed, not qualified.** It again passed installation, main/fallback inference
and worker reload. It recorded one delegation call, but that call did **not**
select the registered `imagepilot` worker. No matching named-worker completion
was confirmed. Do not count an unnamed delegate or the main's response marker
as the required registered-worker result. The available evidence does not settle
the preceding diagnostic run's completion outcome, nor establish a specific
product or Router defect. At that point further diagnosis was needed; no more
retries were started before the next explicit user authorization.

### Authorized diagnosis and successful qualification

After the four failed runs the user explicitly authorized **diagnosis and
correction, without publication**. No product defect was established and no
product patch was necessary. The qualification driver was corrected:

- The request now gives the model the actual tool-schema JSON, with
  `"worker": "imagepilot"` at the top level.
- A `worker` field nested inside `tasks` is no longer accepted as proof of
  worker selection: the product does not support that location.
- Tool results are decoded in their runtime format, including SQLite's
  multimodal sentinel, and composite call IDs are normalized consistently with
  the runtime.
- A completed asynchronous result is matched to the named tool call and its
  originating session. A successful result also requires positive API calls
  and the expected chat model.
- Metadata-only evidence parsing has isolated regression tests for synchronous
  and asynchronous results, wrong sessions/call IDs, nested worker fields,
  multimodal content, missing consumption, errors and echoed markers.

**Successful live run:**
https://github.com/AdMind-ai/marcel-agent/actions/runs/37803721445

Qualification branch commit: `db0b4c7beb8cbf1c474e715e85c71e5802967984`.
The source tag, installed candidate commit and release bytes remain original.

The Ubuntu run passed the collector's 12 simulated fixture tests separately
from the live pilot. An additional local missing-call-ID rejection test makes
13 local tests; this negative-input hardening does not change the successful
run's matched, valid-call-ID path.

The actual live records confirmed:

- One tool call selecting the registered worker at the supported top level.
- One matching tool result with a background dispatch handle.
- One completed asynchronous result, correlated by delegation ID and parent
  session, reporting positive API consumption and `openai/gpt-4.1-nano`.
- No result errors. Both the main and worker configurations were reloaded from
  the installed runtime, not inferred from terminal text.
- Worker permissions: selected tools (`file`, `image_gen`); budgets:
  three API requests and 90 seconds per run; maximum concurrency: one.
- The worker's chat model is separate from its `global` image service. That
  service was not configured because no separate image-service key was supplied.
  The worker was explicitly asked to return a text result without creating an
  image, so this is **chat/delegation qualification**, not image generation.

### Current confirmed and missing evidence

| Check | Outcome |
| --- | --- |
| Original published assets downloaded anonymously and checksummed | Passed, including the successful final run |
| Clean Ubuntu 24.04, normal installer and published candidate commit | Passed |
| Authenticated account catalog | 57 models; catalog membership alone is not execution evidence |
| Main with no workers, `openai/gpt-4.1-nano` | Real response passed |
| Fallback `openai/gpt-4o-mini` | Real explicitly selected model response passed |
| Fallback `openai/gpt-4.1-mini` | Real explicitly selected model response passed |
| Main fallback order | `openai/gpt-4o-mini`, then `openai/gpt-4.1-mini`; saved and reloaded |
| Worker setup and runtime reload | Passed: Router chat LLM, separate global image service, selected tools, request and duration budgets |
| Real execution of the specifically registered image worker | Passed: named call and actual correlated asynchronous completion, with model consumption |
| Actual image generation | Not exercised; separately authorized image-service key absent |
| Automatic failover during a provider failure | Not exercised; explicit model responses do not establish automatic failover |

Only the test account's securely supplied Router key was used. Its temporary
GitHub environment allowed exactly the `qualification/router-rc5` branch, not
tags or other branches. After the completed runs, the remote secret copy and
environment were deleted; a subsequent environment lookup returned HTTP 404.
The environment was recreated with the same restriction for the successful
run, then its secret and environment were again deleted; absence was again
verified. The workspace test key remains in secure storage. Disposable installation HOME,
configuration, sessions and database were not uploaded. Only allowlisted JSON
artifacts were retained.

The public release ID, all five asset IDs, sizes, SHA-256 metadata and update
timestamps were compared before and after the campaign and were unchanged.
Neither product code nor the published tag/assets were changed. No new release
or stable promotion occurred.

An allowlisted local summary with source-run references is retained in
`docs/evidence/rc5-router-live-2026-10-08.json`; it excludes transcripts and
arbitrary provider error messages. The original Actions evidence artifacts have
a seven-day retention period.

No release notes, tag, release assets, public product branch or stable status
were updated. The former public NOT QUALIFIED notice is not silently rewritten;
this report records the narrower subsequent successful Router pilot.

## Earlier failed candidate

See `docs/rc4-router-qualification.md`. Its failed normal-flow result was not
counted as a success or replaced by the passing historical installer/update
harness. rc.4's public notes mark it NOT QUALIFIED; its tag/assets are unchanged.
