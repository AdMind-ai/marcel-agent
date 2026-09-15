#!/usr/bin/env python3
"""Create a deterministic SHA-256 manifest for release artifacts.

The Marcel prerelease process uses SemVer tags even though the legacy release
helper normally creates CalVer tags. The defaults target the next candidate,
``v0.21.0-rc.2``; this script deliberately does not create tags, upload files,
or contact GitHub.

Examples:
    python scripts/release-checksums.py dist/*
    python scripts/release-checksums.py --version 0.21.0 --tag v0.21.0-rc.2 dist/*
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
from pathlib import Path
import subprocess

DEFAULT_VERSION = "0.21.0"
DEFAULT_TAG = "v0.21.0-rc.2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_archive(tag: str, output: Path) -> None:
    """Build a byte-reproducible source archive from a Git tag."""
    prefix = f"marcel-agent-{tag.removeprefix('v')}/"
    try:
        tar_bytes = subprocess.run(
            ["git", "archive", "--format=tar", f"--prefix={prefix}", tag],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"could not archive Git tag {tag!r}") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        # filename="" avoids embedding the destination filename; mtime=0
        # removes wall-clock time. A fixed compression level completes the
        # deterministic gzip envelope around git archive's stable tar stream.
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0
        ) as compressed:
            compressed.write(tar_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument(
        "--build-source-archive",
        type=Path,
        metavar="PATH",
        help="build a deterministic tar.gz from --tag and include it in the manifest",
    )
    parser.add_argument(
        "--output", type=Path, help="write the manifest here (default: stdout)"
    )
    args = parser.parse_args()

    artifact_paths = list(args.artifacts)
    manifest_output = args.output.resolve() if args.output else None
    archive_output = (
        args.build_source_archive.resolve() if args.build_source_archive else None
    )
    reserved_artifacts = [path.resolve() for path in artifact_paths]
    if archive_output:
        reserved_artifacts.append(archive_output)
    if manifest_output and manifest_output in reserved_artifacts:
        parser.error("manifest output must not overwrite a release artifact")

    if args.build_source_archive:
        build_source_archive(args.tag, args.build_source_archive)
        if archive_output not in (path.resolve() for path in artifact_paths):
            artifact_paths.append(args.build_source_archive)

    artifacts = sorted((path.resolve() for path in artifact_paths), key=lambda p: p.name)
    if not artifacts:
        parser.error("at least one release artifact is required")
    missing = [path for path in artifacts if not path.is_file()]
    if missing:
        parser.error("artifact does not exist or is not a file: " + ", ".join(map(str, missing)))
    names = [path.name for path in artifacts]
    if len(names) != len(set(names)):
        parser.error("artifact basenames must be unique for an unambiguous manifest")

    lines = [
        f"# Marcel Agent {args.version} ({args.tag}) release checksums",
        "# SHA-256; filenames are sorted lexicographically.",
    ]
    lines.extend(f"{sha256(path)}  {path.name}" for path in artifacts)
    manifest = "\n".join(lines) + "\n"
    if args.output:
        args.output.write_text(manifest, encoding="utf-8")
    else:
        print(manifest, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())