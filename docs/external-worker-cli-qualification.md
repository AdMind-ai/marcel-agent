# Operator qualification of external worker budgets

This opt-in harness checks **installed, operator-authenticated** Copilot ACP and
Codex app-server CLIs against Marcel's actual transports and worker ledger. It is
not a Router test, an upstream security review, or release qualification.

## Current evidence

The ordinary tests use deterministic offline subprocess peers:

- `tests/agent/transports/test_external_worker_budget.py`
- `tests/tools/test_delegate_external_budget.py`
- `tests/qualification/test_external_worker_qualification.py`

They are regression evidence, **not proof that a particular authenticated CLI
version works**. Neither `copilot` nor `codex` was installed in the implementation
workspace. Real-CLI compatibility remains **not qualified** until an operator
runs the following procedure and reviews both reports. No maintainer account,
temporary bot, provider credential, or passing synthetic live report is shipped.

## Prerequisites and consent

1. Install the actual current CLI from its publisher, and authenticate it yourself
   using its normal local login flow. Authentication must already work without an
   interactive prompt. Use your own operator account, not distribution credentials.
2. Run from a trusted checkout with its Python dependencies installed. Do not run
   another `uv` operation against an environment used by a running gateway.
3. The commands below **make real, potentially billable model calls**. A normal
   run admits six prompts/turns per CLI, but the external agent owns its internal
   model/tool loop. That number is not a provider-request or spending ceiling.
   The deadline/cancellation probes request long output and interrupt it.
4. Use a disposable working environment with no sensitive files. The harness uses
   a temporary working directory, rejects ACP permission prompts through Marcel's
   existing handler, and requests read-only/never-approve Codex configuration.
   It retains your existing authenticated HOME; it does not copy or delete it.
   CLI-owned login/session history remains governed by that CLI.

```sh
python scripts/qualification/external_worker_budget.py \
  --transport acp --run-live --operator-authenticated \
  --report /tmp/marcel-acp-budget.json

python scripts/qualification/external_worker_budget.py \
  --transport codex --run-live --operator-authenticated \
  --report /tmp/marcel-codex-budget.json
```

Use `--command /path/to/copilot` or `--command /path/to/codex` for an installed
executable outside PATH. ACP accepts `--model` for a model available to your
authenticated account; the Codex session uses the CLI's configured model.
`--deadline-seconds` defaults to 8 and `--timeout` to 45 (maximum 300). If startup
takes longer than the deadline, a local forced stop alone does **not** qualify
protocol cancellation: the report fails that check. Adjust and rerun knowingly.

Both consent flags are mandatory; without them no CLI is even resolved.
The harness never installs CLIs or requests/persists credentials.

## Required checks

| Check | Passing evidence |
|---|---|
| Usage and request cap | Two successful prompts with positive, valid usage; ACP per-prompt receipts summed, Codex thread totals monotonic and **not summed**; ledger agrees; third prompt causes no spawn/dispatch. |
| Token cap | A one-token threshold is reached using reported consumption; later dispatch is refused without restarting. This is a threshold, not a prepaid cap. |
| Unobservable tokens | Fault injection removes **only usage metadata** from an actual CLI response/event before the adapter receives it; token budget fails closed and cannot restart. This is labelled fault injection, not native missing-usage evidence. |
| Deadline | Long-running operation expires within the deadline plus five seconds of shutdown tolerance, attempts the correct wire cancellation, leaves no child process alive, and cannot restart. |
| Cancellation acceptance | Separate non-forced probe: ACP prompt actually returns `stopReason=cancelled`, or Codex replies successfully to `turn/interrupt`; a notification write/closed process alone is insufficient. |
| Unobservable USD cost | Monetary budget rejected before any CLI process starts; subscription traffic is never labelled free. |

The separate offline tests cover malformed/missing usage, decreasing cumulative
totals, blocked writes, and stalled handshakes. The opt-in suite does not pretend
to make an authenticated service naturally produce malformed billing data.
Reported final consumption may exceed an admitted threshold. Cancellation cannot
undo work already billed; use provider-side caps for hard spending controls.

## Evidence and exit codes

The JSON contains only the transport, extracted semantic CLI version, named
check outcomes, spawn/dispatch counts and fixed failure codes. No raw wire,
prompts, replies, session identifiers, command arguments, HOME paths, CLI stderr,
or credentials are written. Exception **classes**, not raw backend messages, are
reported. Keep reports outside the checkout; do not commit account state.

- `0`: all six checks passed for that operator command/version.
- `1`: blocked prerequisite or at least one failed/inconclusive check.
- `2`: missing consent or invalid command-line settings.

A version banner does not authenticate a binary. The operator must establish
its publisher/provenance and login separately. A user-supplied fake peer is not
live evidence even if it implements the protocol and returns a successful report.
Record execution date, source revision and CLI provenance in the operator's
review notes; the report alone does not establish release artifact provenance.
