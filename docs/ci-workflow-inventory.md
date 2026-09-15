# CI workflow inventory

This inventory describes the workflows currently present in
`.github/workflows/`. Secret names below are identifiers only; no secret
values are stored in the repository.

| Workflow | Purpose / classification | Secrets | Release relevance |
| --- | --- | --- | --- |
| `ci.yaml` | Main orchestration and aggregate PR gate | None | **Branch protection: `All required checks pass`** |
| `tests.yml` | General Python test suite (called by `ci.yaml`) | None | Aggregate input; release/manual gate |
| `lint.yml` | Ruff and ty static checks (called by `ci.yaml`) | None | Aggregate input; release/manual gate |
| `tests-os.yml` | Linux/macOS/Windows tests (called by `ci.yaml`) | None | Aggregate input; release/manual gate |
| `docs-site-checks.yml` | Documentation checks (called by `ci.yaml`) | None | Aggregate input; release/manual gate |
| `uv-lockfile-check.yml` | Lockfile consistency (called by `ci.yaml`) | None | Aggregate input; release/manual gate |
| `lockfile-diff.yml` | Detects unexpected lockfile changes | None | Release/manual gate |
| `case-collision-check.yml` | Cross-platform path collision guard | None | Recommended |
| `contributor-check.yml` | Contributor attribution validation | None | Recommended |
| `docker-lint.yml` | Docker and shell linting | None | Recommended |
| `installer-tests.yml` | Installer behavior tests | None | Release/manual gate |
| `install-e2e.yml` | Install/update end-to-end coverage | None | Release/manual gate |
| `install-e2e-run.yml` | Reusable install/update E2E implementation | None | Supporting |
| `stable-readiness.yml` | Secret-free immutable-candidate archive, checksum, clean-import, update, and rollback qualification | None | Release/manual gate |
| `windows-venv-e2e.yml` | Windows virtual-environment E2E | None | Release/manual gate |
| `e2e-desktop.yml` | Desktop end-to-end tests | None | Recommended |
| `nix.yml` | Nix flake checks | None | Recommended |
| `rust-tests.yml` | Rust component tests | None | Recommended |
| `profile-artifact-check.yml` | Profile artifact boundary guard | None | Recommended |
| `osv-scanner.yml` | Dependency vulnerability scan | None | Release/manual gate |
| `supply-chain-audit.yml` | Supply-chain and dependency audit | None | Release/manual gate |
| `history-check.yml` | Repository history policy checks | None | Recommended |
| `infographic-check.yml` | Infographic asset validation | None | Optional |
| `skills-index-freshness.yml` | Skills index freshness check | `APP_PRIVATE_KEY` | Recommended |
| `skills-index.yml` | Builds/publishes skills index | `APP_PRIVATE_KEY` | Release-adjacent |
| `publish-e2e-evidence.yml` | Publishes E2E evidence | `GH_IMAGE_SESSION_TOKEN` | Release-adjacent |
| `docker.yml` | Docker build, test, and publish | `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` | Release |
| `deploy-site.yml` | Documentation/site deployment | `APP_PRIVATE_KEY`, `VERCEL_DEPLOY_HOOK` | Release |
| `js-tests.yml` | JavaScript tests | None | Aggregate input; release/manual gate |
| `js-autofix.yml` | Automated JS formatting fixes | `APP_PRIVATE_KEY`, `GITHUB_TOKEN` | Non-blocking automation |
| `ci-review-comment.yml` | Posts CI review comments | `GITHUB_TOKEN` | Non-blocking automation |
| `label-rerun.yml` | Reruns labeling automation | `GITHUB_TOKEN` | Non-blocking automation |
| `review-labels.yml` | Applies review labels | `GITHUB_TOKEN` | Non-blocking automation |

## Recommended protected-branch and release checks

For pull requests, branch protection should require only the aggregate check
**`All required checks pass`**, emitted by `ci.yaml`. The aggregate evaluates
the applicable validation lanes, so individual reusable workflows must not be
added as separate required checks. Workflows without pull-request triggers
cannot be PR requirements; use them as release/manual gates instead.

For a release, run the applicable validation lanes before publishing, then use
`docker.yml`, `deploy-site.yml`, and other release/manual gates when their
artifacts are part of the release. Keep publish jobs protected by their
existing environment and repository conditions; do not make credentials a
pull-request requirement.

`stable-readiness.yml` is an evidence-only manual gate. It accepts an existing
immutable candidate tag or full commit SHA, performs no tag creation or
publishing, and does not replace the credentialed Docker/site gates.

This is an inventory, not a workflow policy change. The stable-readiness lane
is manual and read-only; GitHub-provided `GITHUB_TOKEN` is listed only where
referenced explicitly.