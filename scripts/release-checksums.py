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
import hashlib
from pathlib import Path

DEFAULT_VERSION = "0.21.0"
DEFAULT_TAG = "v0.21.0-rc.2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument(
        "--output", type=Path, help="write the manifest here (default: stdout)"
    )
    args = parser.parse_args()

    artifacts = sorted((path.resolve() for path in args.artifacts), key=lambda p: p.name)
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