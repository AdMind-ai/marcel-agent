# Launch dependency review — 2026-10-07

This is a dependency review, not a certification that the whole product is
secure. GitHub CI and install/update qualification must pass on the final
release commit before publishing a stable version.

## Remediations

- Incorporate the pending Dependabot updates while keeping Electron's installed
  version, builder version, and install-script allowlist consistent.
- Raise patched floors for PyJWT, urllib3, OAuthlib, Tornado, DOMPurify,
  fast-uri, brace-expansion, ip-address, undici, gRPC, Axios, simple-git, KaTeX,
  HTTP cache semantics, Joi, PostCSS selectors, shell-quote, source-map-js,
  compression, proxy-addr, and Tinypool.
- Keep the normal dependency age gate; exempt only the named security fixes.
- Check every resolved copy in the lockfiles, not just package.json overrides.
- Do not disable scanners or dismiss alerts to achieve a green result.

## Open upstream findings

`braces` 3.0.3 has a stack-exhaustion advisory and no patched release available
as of this review. The website lockfile's high findings propagate from this
single package through its globbing/build-tool parents. The website is built
from repository files into static output: the build tooling is not a server
handling visitors' glob patterns. Do not process untrusted glob patterns in
production or build untrusted repositories with privileged credentials.
Recheck the upstream fix and the actual deployment boundary before stable;
this finding is **not fixed or dismissed**.

`sprintf-js` 1.1.3 also has an advisory with no patched release available.
The root lockfile retains moderate findings propagated through its tooling
parents. Do not describe the dependency audit as clean. Recheck upstream and
verify the installed application's exposure before stable.

PyJWT's new options-dictionary mutation advisory has no published patched
version. Existing decode call sites construct fresh options per call; do not
reuse options dictionaries across JWT verifications. Recheck upstream before
stable even though 2.15.0 resolves the other JWT advisories.

## Scheduled install/update qualification

An upgrade must start from a commit different from its target. Tag aliases
(including annotated tags) can point at the same commit as main after a
release. The selector excludes all such aliases by resolved commit before
sampling history; it continues to test genuine older-to-newer upgrades.
This does not replace candidate clean-install qualification or change the
published release assets.
