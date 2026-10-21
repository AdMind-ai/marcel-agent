"""A fresh Windows-style clone must remain clean before pinned checkout."""

import os
import subprocess


def test_clone_sets_autocrlf_before_first_checkout(tmp_path):
    global_config = tmp_path / "gitconfig"
    global_config.write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(global_config)}
    source = tmp_path / "source"
    source.mkdir()

    def git(*args, cwd=source):
        return subprocess.run(
            ["git", *args], cwd=cwd, env=env, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    # Author LF blobs without relying on the simulated global CRLF setting.
    git("config", "core.autocrlf", "false")
    for filename in ("uv.lock", ".npmrc"):
        (source / filename).write_bytes(b"base\n")
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "candidate")
    for filename in ("uv.lock", ".npmrc"):
        (source / filename).write_bytes(b"candidate\n")
    git("commit", "-qam", "candidate")
    target = git("rev-parse", "HEAD")
    clone = tmp_path / "clone"
    git("clone", "--branch", "main", "--config", "core.autocrlf=false",
        str(source), str(clone), cwd=tmp_path)
    assert git("status", "--porcelain", cwd=clone) == ""
    assert (clone / "uv.lock").read_bytes() == b"base\n"
    git("checkout", "--detach", target, cwd=clone)
    assert git("rev-parse", "HEAD", cwd=clone) == target
    assert git("status", "--porcelain", cwd=clone) == ""
