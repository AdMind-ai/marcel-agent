# Launch dependency review — 2026-10-08

This is a dependency review, not a certification that the whole product is
secure. GitHub CI and install/update qualification must pass on the final
release commit before publishing a stable version.

## Remediations

- Incorporate the pending Dependabot updates while keeping Electron's installed
  version, builder version, and install-script allowlist consistent.
- Raise patched floors for PyJWT, urllib3, OAuthlib, Tornado, DOMPurify,
  fast-uri, brace-expansion, ip-address, undici, gRPC, Axios, simple-git, KaTeX,
  HTTP cache semantics, Joi, PostCSS selectors, shell-quote, source-map-js,
  compression, proxy-addr, and Tinypool. Update global-agent to remove the
  vulnerable sprintf-js/roarr tooling chain.
- Keep the normal dependency age gate; exempt only the named security fixes.
- Check every resolved copy in the lockfiles, not just package.json overrides.
- Do not disable scanners or dismiss alerts to achieve a green result.

## Decision and release boundary

**Assessment complete; stable publication is not authorized by this review.**
There are three distinct outcomes:

1. `braces` remains an **open high finding**, conditionally tolerable only in
   an isolated, trusted-source static build. The conditions below are release
   gates, not an alert dismissal or an assertion that the package is safe.
2. The locked PyJWT **2.15.0 distribution actually copies `options`**. The old
   statement that there is no released implementation of that fix was wrong.
   Preserve fresh per-call dictionaries as defense in depth; retain the
   advisory's incomplete patch metadata in the assessment.
3. The latest public prerelease, **v0.21.0-rc.5**, still ships PyJWT **2.13.0**.
   It must **not** be promoted to stable. A newly qualified candidate containing
   the remediated pins/lockfiles is required. Do not overwrite the existing
   immutable prerelease assets.

The release owner must explicitly approve any residual `braces` risk on the
final release commit, after the static-host/build-isolation evidence is
available. No such approval or stable release was performed here.

## Upstream recheck and dependency evidence

Public advisory APIs, registry metadata and distribution bytes were checked
on **2026-10-08**:

| Item | Evidence | Result |
| --- | --- | --- |
| `braces` | [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), CVE-2026-93687, CWE-674 | High; affected `<=3.0.3`; `first_patched_version: null`. |
| Upstream `braces` | [issue #70](https://github.com/micromatch/braces/issues/70), [npm latest](https://registry.npmjs.org/braces/latest) | Issue open; latest 3.0.3. No published upgrade fixes the finding. |
| Build-tool parent | [Docusaurus core latest](https://registry.npmjs.org/@docusaurus/core/latest) | Latest 3.10.2, already pinned; no newer parent release removes the chain. |
| PyJWT options | [GHSA-gvp8-978c-rx2q](https://github.com/advisories/GHSA-gvp8-978c-rx2q) | Medium; published affected range `>=2.11.0, <=2.13.0`; patch-version field remains null. Advisory references a prepared [fix](https://github.com/jpadilla/pyjwt/commit/0c87c8c8b1a74cac99ad8115f3050efcb7fbed35). |
| Released PyJWT | [2.15.0 metadata](https://pypi.org/pypi/PyJWT/2.15.0/json), [latest metadata](https://pypi.org/pypi/PyJWT/json) | Latest is 2.15.1; both wheels copy the input in `_merge_options`. The already-locked 2.15.0 wheel **and sdist** contain the fix, so no unrelated version change is needed for this assessment. |

Fresh `npm audit --json` results from the checked-in lockfiles:

| Directory | Findings |
| --- | --- |
| Repository root | 0 |
| `plugins/platforms/photon/sidecar` | 0 |
| `website` | 30 high, 0 critical; one underlying `braces` advisory propagated to build-tool parents, `fixAvailable: false` |

These counts are dated observations, not a permanent assurance. The website
audit exits nonzero and is **not clean**. `braces` is pulled through
`micromatch`/`chokidar`; it is present only in the website among the four
Marcel npm lockfiles checked (root, website, Photon, WhatsApp bridge). npm
classifies much of the website tooling as production dependencies because
Docusaurus is under `dependencies`: `--omit=dev` is **not** a mitigation.
The separate workspace scaffold is not a Marcel release/runtime boundary.

## `braces`: reachability and build isolation

The issue exhausts Node's stack on deeply nested **patterns**; the relevant
impact is build-process denial of service, not a demonstrated credential
exfiltration. The containment must nevertheless avoid privileged credentials
and unreviewed code during any vulnerable build.

Inspected entry points:

- `website/package.json` builds with `docusaurus build`; the locale-limited
  CI build uses `docusaurus build --locale en`. `website/docusaurus.config.ts`
  configures static documentation and client redirects, not a visitor-facing
  glob API or an SSR server.
- `website/scripts/prebuild.mjs` runs repository-owned Python generators.
  The skill generator's filesystem pattern is the literal `SKILL.md`.
  Catalog downloads are JSON content, not user-supplied Docusaurus/glob
  configuration. No request or catalog field was found being passed as a
  glob pattern in these build entry points.
- `.github/workflows/docs-site-checks.yml` builds on an ephemeral runner,
  with read-only repository permissions and no provider/App secrets.
  PR builds must never receive secret inheritance or write credentials.
- `.github/workflows/deploy-site.yml` now separates `build-docs` from
  `deploy-docs`. The build has only `contents: read`/`actions: read`, disables
  checkout credential persistence, and no longer obtains a GitHub App token
  or private key. The short-lived read-only workflow token is scoped to the
  catalog-preparation step, not npm install/build. Only `_site`, populated
  from `website/build` plus retained static assets, crosses into publication.
- The publication job has Pages/OIDC write permissions but **no checkout,
  npm installation, build, or glob tooling**. The Vercel-hook job is separate
  and does not execute the website build.

**Limits of confirmation:** the Pages jobs are guarded for
`NousResearch/hermes-agent`, not the Marcel fork. The Vercel job merely calls
an externally configured hook. A hook URL does not prove that the remote
project has a static output directory, trusted production branch, isolated
preview builds, or no privileged build-time secrets. Remote Vercel settings
and an actual successful deployment of this revised workflow were not
available as evidence here. Do not claim the live Marcel website boundary
has been verified from this workflow alone.

Residual-risk conditions for the release owner:

- Build only reviewed release/main sources for publication; do not build
  arbitrary repositories, PR code, or attacker-controlled pattern/config
  inputs with privileged credentials. Keep any untrusted previews isolated.
- Host only generated static output. Do **not** deploy `docusaurus start`,
  `docusaurus serve`, the dependency tree, or a Node/glob endpoint as the
  production application.
- Record the actual host's output directory, production ref and build-secret
  policy, plus a successful build/publication run on the candidate commit.
  GitHub Pages isolation is implemented here, but does not certify Vercel.
- Recheck the upstream advisory/registry immediately before stable and weekly
  while accepted. Reopen the decision as soon as a patched compatible
  `braces`/parent release exists, or if any of the above boundaries changes.
  The release owner owns this check and must withhold stable approval if the
  evidence or isolation is missing.

## JWT call-site review

An AST inventory of all tracked non-test Python files found **four decode
calls in three functions**, plus one signing call. The same complete inventory
was checked inside the downloaded public source archive.

| Entry point | Verification and options lifetime |
| --- | --- |
| `plugins/dashboard_auth/_shared.py::verify_jwt` | Signed verification uses configured algorithms, audience and issuer with a fresh `{"require": ["exp", "iat", "aud", "iss", "sub"]}`. A separate fresh unsigned dictionary is used only after verification fails, for error diagnostics; those claims are never returned as an authenticated session. Nous and self-hosted dashboard providers share this verifier. |
| `plugins/cron_providers/chronos/verify.py::verify_nas_fire_token` | Each invocation creates new `decode_kwargs` and nested `options`, requires `exp`/`aud`, pins asymmetric algorithms and audience, checks issuer when configured and the `cron_fire` purpose, and fails closed on missing keys or verification errors. The cached object is a JWKS client, **not** an options dictionary. |
| `tools/skills_sync_client.py::resolve_identity` | A fresh unsigned options literal extracts owner/admin metadata for client-side sync gating. This is **not JWT authentication**: the original bearer is sent to the remote sync service, which must enforce authorization. Do not treat the local admin flag as proof of privilege or reuse these options in a signed verifier. |
| `tools/skills_hub_github.py` | `jwt.encode(..., algorithm="RS256")` signs a GitHub App assertion; it does not decode tokens or share decode options. |

`marcel_cli/dashboard_auth/base.py` imports JWT exception classes only.
PyJWT's internal JWKS-header/payload peek also supplies its own fresh unsigned
options literal in the inspected 2.15.0 wheel. Hand-parsed OAuth expiry/claim
helpers are not PyJWT verifiers and are outside this options-mutation advisory.

`tests/test_launch_security_boundaries.py` locks down the decode inventory,
fresh-options construction, website-only npm dependency boundary, and
separation of unprivileged build from privileged publication. Its real PyJWT
test exercises **both** `decode` and `decode_complete`: unsigned peeks do not
modify the caller dictionary, and reuse after re-enabling verification rejects
expired, future-not-before, future-issued-at, wrong-audience, wrong-issuer,
invalid-subject and invalid-JTI tokens.

## Effective distributions, not just manifests

The working tree specifies `pyjwt[crypto]==2.15.0`; `uv.lock` resolves 2.15.0.
Downloaded directly from the **lockfile URLs**, both artifacts matched their
locked SHA-256:

- `pyjwt-2.15.0-py3-none-any.whl`:
  `7a3742debf6b879e912dbb9819ceec1594be812452b78c5f2e2dfc56564954f8`
- `pyjwt-2.15.0.tar.gz`:
  `b11c5f9791d7bf51c2b39a81ed669f6b2dbbd669df2942f6c60167e9e3d1abe4`

Both contain `merged_options = ... dict(options)` before adding defaults.
The regression test was run with this exact downloaded 2.15.0 wheel, not a
pre-existing environment or an assumed upstream branch.

The latest public release API lists only prereleases; `/releases/latest`
returns 404 because there is no stable release. The actual explicit
[rc.5 source asset](https://github.com/AdMind-ai/marcel-agent/releases/download/v0.21.0-rc.5/marcel-agent-v0.21.0-rc.5.tar.gz)
was downloaded and checked against its published `SHA256SUMS`:

`d86ebae9d79903663e468374df2a469e9b621e20aabdd77640fbde6560337dad`

Its manifest and lock still resolve **2.13.0**, with wheel hash
`66adcc2aff09b3f1bbd95fc1e1577df8ac8723c978552fd43304c8a290ac5728`.
Its three decoding modules are byte-identical to the reviewed working copies,
so fresh options mitigate this particular reuse bug, **not the other 2.13.0
JWT advisories**. The archive contains website source/lockfiles but no installed
`node_modules`; including build-source files is not proof of a Node runtime
or of a safe remote deployment.

Before stable, download the **new candidate's actual assets**, verify checksums,
inspect their manifest/lock and JWT modules, and qualify a clean installation
with the resolved PyJWT version. Local manifest fixes and regenerated archives
do not prove the published package has changed.

## Scanner policy and remaining gates

No alerts were dismissed, advisory IDs ignored, scanner paths excluded, or
scanner settings weakened. OSV still scans all five configured lockfiles and
uploads findings to Security. Its existing detection-only
`fail-on-vuln: false` setting is unchanged: a green job is **not** absence of
vulnerabilities and does not approve stable publication.

Repeat on the final candidate:

```sh
npm audit --json
npm audit --prefix website --json
npm audit --prefix plugins/platforms/photon/sidecar --json
python -m unittest tests.test_launch_security_boundaries -v
```

Run the Python check in the qualified candidate environment with its locked
PyJWT and PyYAML (already declared dependencies). Expect the website audit to
remain nonzero until upstream is patched. Require final CI/install-update
qualification, actual downloaded-asset verification, host-isolation evidence
and explicit owner approval of the scoped residual risk before stable.

## Scheduled install/update qualification

An upgrade must start from a commit different from its target. Tag aliases
(including annotated tags) can point at the same commit as main after a
release. The selector excludes all such aliases by resolved commit before
sampling history; it continues to test genuine older-to-newer upgrades.
This does not replace candidate clean-install qualification or change the
published release assets.
