"""Prevent a manifest-only security bump from retaining vulnerable lock entries."""

import json
from pathlib import Path
import tomllib

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "lockfile,floors",
    [
        ("package-lock.json", {
            "electron": (41, 10, 6),
            "dompurify": (3, 4, 16),
            "brace-expansion": (5, 0, 12),
            "fast-uri": (3, 1, 8),
            "ip-address": (10, 7, 2),
            "axios": (1, 20, 0),
            "global-agent": (4, 1, 3),
            "simple-git": (4, 0, 2),
            "katex": (0, 18, 2),
        }),
        ("website/package-lock.json", {
            "dompurify": (3, 4, 16),
            "brace-expansion": (5, 0, 12),
            "fast-uri": (3, 1, 8),
            "http-cache-semantics": (4, 3, 0),
            "tinypool": (2, 1, 2),
            "proxy-addr": (2, 0, 8),
        }),
        ("plugins/platforms/photon/sidecar/package-lock.json", {
            "@grpc/grpc-js": (1, 14, 5),
            "undici": (7, 30, 0),
        }),
    ],
)
def test_patched_npm_floors_apply_to_every_resolved_copy(lockfile, floors):
    packages = json.loads((ROOT / lockfile).read_text())["packages"]
    for name, floor in floors.items():
        copies = [
            entry for path, entry in packages.items()
            if path.endswith(f"node_modules/{name}")
        ]
        assert copies, f"{name} missing from {lockfile}"
        for entry in copies:
            version = tuple(int(part) for part in entry["version"].split("."))
            assert version >= floor, (lockfile, name, entry["version"], floor)


def test_patched_python_dependencies_are_resolved():
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    floors = {"pyjwt": (2, 15, 0), "urllib3": (2, 8, 0), "tornado": (6, 5, 9),
              "oauthlib": (4, 0, 0)}
    resolved = {entry["name"]: entry["version"] for entry in lock["package"]}
    for name, floor in floors.items():
        assert tuple(int(part) for part in resolved[name].split(".")) >= floor
