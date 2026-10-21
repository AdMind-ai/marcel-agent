# Router qualification: v0.21.0-rc.4

## Status

**Incomplete: the normal-install live pilot failed; rc.4 is not qualified.**
This report must not be used as approval to publish a stable release.

The user approved publication of this prerelease on 2026-10-07. No stable
publication has been approved.

- Public release: https://github.com/AdMind-ai/marcel-agent/releases/tag/v0.21.0-rc.4
- Candidate commit: `3cb4314467db24f94e216e8bf417c97037afa994`
- Public candidate branch: `release/v0.21.0-rc.4`
- Base: the public `main` commit used by `v0.21.0-rc.3`.

The release was built on the public repository baseline, not the workspace's
older mirror. The worker controls were integrated while retaining public
onboarding fixes. The workspace artifacts, personal runtime state and agent
memory were excluded from the candidate.

## Completed checks

### Simulated checks — not live qualification

145 tests passed for setup, Router validation/provider configuration, worker
registry, worker limits and worker screens. The focused run included:

- `tests/marcel_cli/test_setup_worker_controls.py`
- `tests/marcel_cli/test_setup_marcel.py`
- `tests/tools/test_delegate_worker_limits.py`
- `tests/tools/test_delegate_worker_registry.py`
- `tests/marcel_cli/test_router_provider.py`
- `tests/test_marcel_router_validator.py`

Prompt/network replacements in these tests do **not** establish that the
account's real models, fallback requests, normal installer or worker execution
work on clean Ubuntu.

Integration preserves capability-aware image/vision selection, global image
services and the main-agent-first setup sequence. Catalog labels support both
list and mapping capability metadata, and account availability/alias metadata.
The live catalog is scoped to a single wizard run, including early returns.

### Actual public asset checks

Downloaded anonymously from the published release:

- `install.cmd`
- `install.ps1`
- `install.sh`
- `marcel-agent-v0.21.0-rc.4.tar.gz`
- `SHA256SUMS`

The downloaded manifest covers each of the four other assets exactly once.
All four SHA-256 digests match the downloaded bytes. The downloaded source
archive opens successfully and does not include the excluded root-level
workspace directories or runtime credential files.

The release is public, not a draft, and is marked as a prerelease.

### Live endpoint checks — unauthenticated only

- `https://marcel-agent.com/api/healthz`: HTTP 200.
- `https://marcel-agent.com/api/v1/models`: HTTP 401 without credentials.

These prove reachability and an authentication boundary, not authenticated
discovery or inference.

### Authenticated live discovery and clean Ubuntu pilot

With the user-supplied test credential, the actual Router returned **57 models**.
No maintainer provider credential was used.

The clean Ubuntu 24.04 pilot downloaded and verified the published assets,
authenticated against the real Router, and launched the normal installer
under a PTY, without `--skip-setup` or `--non-interactive`.

Run: https://github.com/AdMind-ai/marcel-agent/actions/runs/37661899084

**Result: failed; not an installed-runtime success.** The installer launches
setup through `python -m marcel_cli.main`. Product detection in the setup wizard
uses the executable name, so that invocation opens the legacy "Quick setup /
Full setup / Blank Slate" chooser instead of the Marcel-specific onboarding.
The terminal driver then timed out on that chooser. Its recorded failure is
`TIMEOUT`; do not mislabel this as a Router authentication failure.

Main inference, zero-worker persistence, image-worker configuration, fallback
ordering and installed-runtime reload were **not reached** in this live run.
Their simulated tests remain passing but do not replace these missing results.

The release notes now explicitly mark rc.4 **NOT QUALIFIED**. The tag and the
five published assets have not been replaced or changed. A corrected candidate
requires separate publication approval.

Cleanup: the temporary GitHub environment and its sealed Router credential
copy were deleted after the failed run. The driver's disposable HOME was
removed. Only allowlisted JSON evidence was uploaded; no `.env`, config,
sessions or runtime logs were retained.

## Remaining live qualification

After approval of the correction and its publication, use a clean Ubuntu runner
and the new candidate's actual published assets. The following command is only
for reproducing rc.4's failure. Do not replace published assets
them with an archive rebuilt locally, a fixture Router or a modified source
checkout. Exercise the normal installer, without `--skip-setup` or
`--non-interactive`:

```sh
curl -fsSL \
  https://github.com/AdMind-ai/marcel-agent/releases/download/v0.21.0-rc.4/install.sh \
  -o /tmp/marcel-install-rc4.sh
bash /tmp/marcel-install-rc4.sh --branch v0.21.0-rc.4
```

Required evidence:

1. Anonymous asset download, checksum verification and normal installation.
2. Actual Router authentication and the test account's model catalog.
3. Main-agent setup and an actual response with no workers.
4. Reconfiguration with an image worker using an executable chat/tool LLM,
   with the generation service separate from the worker model.
5. Primary and fallback IDs present and available in the authenticated catalog,
   with the exact selected fallback order.
6. Saved configuration reloaded through the installed runtime; no raw keys in
   YAML, templates, release assets or retained evidence.
7. Clearly label any fallback failure injection or replaced image operation
   as simulated, rather than presenting it as a live provider result.

The Router test key has been supplied through secure secret storage for the
approved test account. Its workspace secret was not deleted; only the temporary
GitHub copy was removed. Do not substitute existing maintainer provider
credentials. Actual image generation additionally requires a separately
authorized registered image service; a worker's chat model is not that service.

The tag-triggered Install & Update E2E run passed:
https://github.com/AdMind-ai/marcel-agent/actions/runs/37658446938
Its installer/update harness is distinct from this authenticated normal-flow
qualification; do not count it as live Router evidence.
