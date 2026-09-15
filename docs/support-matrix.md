# Marcel support matrix

This is the support target for the current Marcel prerelease line. It is
deliberately not a claim that `0.21.0` is a stable release: no stable package
artifact has been published yet. The matrix records where the source
distribution is intended to work and what the no-credential qualification
job checks.

## Core runtime

| Platform | Python | Install path | Qualification status |
| --- | --- | --- | --- |
| Linux x86_64 | 3.11, 3.12, 3.13 | `scripts/install.sh` | Candidate installer E2E lane; archive CLI qualification runs on Ubuntu |
| macOS x86_64 and arm64 | 3.11, 3.12, 3.13 | `scripts/install.sh` | Candidate installer E2E lane; not an archive-install claim |
| Windows x86_64 | 3.11, 3.12, 3.13 | `scripts/install.ps1` | Candidate installer E2E lane; not an archive-install claim |

The declared interpreter range is `>=3.11,<3.14`. A platform is supported
only for the core CLI and its declared dependencies. Optional providers,
messaging adapters, browser automation, audio/video tools, and native
packages can have narrower platform or system requirements; their
qualification is not implied by this table.

The source archive is a reproducibility and clean-CLI qualification input. It
is not a separately published wheel or a promise that `pip install` is a
supported public distribution path.

## Qualification boundaries

The stable-readiness workflow is intentionally secret-free. It proves:

- an operator supplied an existing immutable candidate tag or full commit;
- the candidate source archive is reproducible and its SHA-256 manifest verifies;
- a clean archive install can import the core packages;
- historical update and rollback evidence exists for the selected release
  history.

It does **not** prove provider connectivity, account setup, billing, OAuth,
desktop packaging, Docker images, website deployment, or production
performance. Those require credentials or operational environments and remain
separate release gates.

### Credential requirements

| Surface | Credentials in qualification? | Meaning |
| --- | --- | --- |
| Source archive, manifest, install, core imports | No | Public source and package metadata only |
| `marcel doctor` with no configured provider | No | Configuration diagnostics only |
| Router/provider calls | Yes | Bring a provider credential and endpoint |
| Google, IMAP/SMTP, messaging, or browser integrations | Yes | Configure the corresponding account and optional dependencies |
| Docker and documentation/site publishing | Yes | Existing release paths; not part of this package |

Until the workflow, release evidence, and operational blockers below are
closed, Marcel remains a public prerelease rather than a stable supported
package.

## Remaining stable-release gates

Before announcing a stable release, attach the workflow run and checksum
manifest to the release notes, review the update/rollback evidence, and
confirm that the release owner has completed the credentialed provider,
Docker, and site gates. This package does not publish an artifact, configure
signing, or alter either publish path.