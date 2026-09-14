# Changelog

All notable changes to Marcel Agent will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/) for published
releases. Marcel is currently in public prerelease; no stable supported package
artifact has been announced yet.

## Unreleased

## 0.21.0-rc.2

### Added

- Expanded the public Marcel Router contract to cover realtime voice, asynchronous
  video, embeddings, moderation, reranking, translation, and search/data tools.

### Fixed

- Restored clean-install qualification for the current release candidate.
- Restored both supported update routes from `v0.21.0-rc.1`: `marcel update`
  and re-running the installer over an existing checkout.
- Preserved user changes during updates while allowing a newly created clone to
  normalize checkout metadata before pinning its candidate commit.
- Stabilized historical installer qualification across PowerShell line endings,
  executable sandbox helpers, legacy migration bootstrap, and npm registry TLS.

## 0.21.0-rc.1 (first public prerelease)

`v0.21.0-rc.1` is the first public Marcel prerelease. Version `0.21.0`
continues the upstream runtime lineage while Marcel establishes its own
release and package metadata. The prerelease tag uses SemVer rather than the
legacy CalVer tags used for normal upstream weekly releases.

### Added

- Marcel-owned runtime, CLI, setup flow, router contract, worker registry, and
  deterministic `cheapest_capable` routing policy.
- Dedicated personal or business single-tenant deployment model.
- Apache-2.0 licensing for Marcel work with separate upstream MIT notices.

### Security

- Private vulnerability reporting through GitHub Security Advisories and
  `security@marcel-agent.com`.

### Documentation

- Explicit distinction between implemented router endpoints and planned media
  contract extensions.
- Official website, routing, dashboard, billing, API key, and usage URLs.

## Release policy

The first stable public release will include:

- signed or checksummed release artifacts;
- a tested platform-support matrix;
- clean-install verification;
- documented update and rollback procedures;
- release notes linked to the corresponding tag.