"""Focused contracts for the pre-tag release qualification paths."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = REPO_ROOT / ".github/scripts/validate-doctor.py"
_SPEC = importlib.util.spec_from_file_location("validate_doctor", VALIDATOR_PATH)
assert _SPEC and _SPEC.loader
validate_doctor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validate_doctor)


def test_rc2_release_defaults_and_vercel_hook_policy_are_explicit():
    checksum_script = (REPO_ROOT / "scripts/release-checksums.py").read_text()
    deploy_workflow = (REPO_ROOT / ".github/workflows/deploy-site.yml").read_text()

    assert 'DEFAULT_TAG = "v0.21.0-rc.2"' in checksum_script
    assert "VERCEL_DEPLOY_HOOK: ${{ secrets.VERCEL_DEPLOY_HOOK }}" in deploy_workflow
    assert 'if [ -z "$VERCEL_DEPLOY_HOOK" ]' in deploy_workflow
    assert "release publication will not trigger Vercel" in deploy_workflow
    assert 'https://*) ;;' in deploy_workflow
    assert 'curl -fsS --retry 3 --retry-delay 10 -X POST "$VERCEL_DEPLOY_HOOK"' in deploy_workflow


def test_installers_retain_anonymous_fresh_clone_and_pinned_commit_paths():
    shell = (REPO_ROOT / "scripts/install.sh").read_text()
    powershell = (REPO_ROOT / "scripts/install.ps1").read_text()

    for installer in (shell, powershell):
        assert "fresh install/archive download is disabled" not in installer
        assert "AdMind-ai/marcel-agent.git" in installer
        assert "Commit" in installer
    assert 'git clone --depth 1 --branch "$BRANCH"' in shell
    assert "git -c windows.appendAtomically=false clone --depth 1 --branch $Branch" in powershell
    assert '--commit expects a hex SHA' in shell
    assert 'git checkout --detach "$INSTALL_COMMIT"' in shell
    assert 'git ... checkout --detach $Commit' not in powershell
    assert 'checkout --detach $Commit' in powershell
    assert "private repo" not in shell.lower()
    assert "private repo" not in powershell.lower()


def test_release_tag_picker_uses_semver_precedence(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "test"],
        check=True,
    )
    (repo / "file").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "file"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    tags = ["v0.21.0-rc.1", "v0.21.0", "v2026.4.13", "v2026.4.8", "v0.21.0-rc.2"]
    for tag in tags:
        subprocess.run(["git", "-C", str(repo), "tag", tag], check=True)

    script = REPO_ROOT / "scripts/sandbox/pick-release-tags.sh"
    result = subprocess.run(
        [str(script), "--repo", str(repo), "--count", "5"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == (
        '["v0.21.0-rc.1","v0.21.0-rc.2","v0.21.0",'
        '"v2026.4.8","v2026.4.13"]'
    )

    result = subprocess.run(
        [
            str(script),
            "--repo",
            str(repo),
            "--count",
            "5",
            "--exclude-tag",
            "v0.21.0-rc.2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == (
        '["v0.21.0-rc.1","v0.21.0","v2026.4.8","v2026.4.13"]'
    )

    first_release_repo = tmp_path / "first-release"
    first_release_repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(first_release_repo)], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(first_release_repo),
            "config",
            "user.email",
            "test@example.invalid",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(first_release_repo), "config", "user.name", "test"],
        check=True,
    )
    (first_release_repo / "file").write_text("x")
    subprocess.run(
        ["git", "-C", str(first_release_repo), "add", "file"], check=True
    )
    subprocess.run(
        ["git", "-C", str(first_release_repo), "commit", "-qm", "initial"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(first_release_repo), "tag", "v0.21.0-rc.1"],
        check=True,
    )
    result = subprocess.run(
        [
            str(script),
            "--repo",
            str(first_release_repo),
            "--exclude-tag",
            "v0.21.0-rc.1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "[]"


def test_tag_trigger_excludes_the_current_release_from_update_sources():
    workflow = (REPO_ROOT / ".github/workflows/install-e2e.yml").read_text()

    assert '[[ "$GITHUB_REF_TYPE" == "tag" ]]' in workflow
    assert 'picker_args+=(--exclude-tag "$GITHUB_REF_NAME")' in workflow
    assert "CANDIDATE_REF: ${{ inputs.candidate-ref }}" in workflow
    assert '[[ "$GITHUB_EVENT_NAME" == "workflow_dispatch" ]]' in workflow
    assert 'git show-ref --verify --quiet "refs/tags/$CANDIDATE_REF"' in workflow
    assert 'picker_args+=(--exclude-tag "$CANDIDATE_REF")' in workflow


def test_workflow_doctor_policy_is_strict_and_secret_free():
    workflow = (REPO_ROOT / ".github/workflows/install-e2e.yml").read_text()
    assert "NO_COLOR=1 marcel doctor" in workflow
    assert "doctor_status=$?" in workflow
    assert "$doctorExit = $LASTEXITCODE" in workflow
    assert "validate-doctor.py" in workflow
    assert "github.workflow_sha" in workflow
    assert "path: .qualification-candidate" in workflow
    assert "CANDIDATE_DIR" in workflow
    assert "Capture trusted Python" in workflow
    assert "steps.trusted-python-unix.outputs.path" in workflow
    assert "steps.trusted-python-windows.outputs.path" in workflow
    assert "Get-Command python -CommandType Application |" in workflow
    assert "Select-Object -First 1 -ExpandProperty Source" in workflow
    assert '[IO.Path]::GetExtension($python) -ne ".exe"' in workflow
    assert "Test-Path -LiteralPath $python -PathType Leaf" in workflow
    assert "(Get-Command python -CommandType Application).Source" not in workflow
    assert "TRUSTED_PYTHON" in workflow
    assert "RUNNER_TEMP/marcel-doctor.txt" in workflow
    assert "marcel-doctor.status" in workflow
    assert workflow.index("path: .qualification-candidate") < workflow.index(
        "path: .qualification-trusted"
    )
    assert "persist-credentials: false" in workflow


@pytest.fixture
def pristine_doctor_output() -> str:
    return "\n".join(
        [
            "◆ Required Packages",
            "✓ OpenAI SDK",
            "✓ Rich (terminal UI)",
            "✓ python-dotenv",
            "✓ PyYAML",
            "✓ HTTPX",
            "⚠ Config version outdated (v0 → v40) (new settings available)",
            "✗ Marcel identity and configuration (not configured)",
            "Found 2 issue(s) to address:",
            "1. Run 'marcel doctor --fix' or 'marcel setup' to migrate config",
            "2. Run `marcel setup` to create Marcel configuration.",
            "Tip: run 'marcel doctor --fix' to auto-fix what's possible.",
        ]
    )


def test_doctor_validator_accepts_pristine_status_zero_and_one(pristine_doctor_output):
    validate_doctor.validate(pristine_doctor_output, 0)
    validate_doctor.validate(pristine_doctor_output, 1)


def test_doctor_validator_rejects_other_exit_status(pristine_doctor_output):
    with pytest.raises(ValueError):
        validate_doctor.validate(pristine_doctor_output, 2)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace("✗ Marcel", "✗ Extra\n✗ Marcel"),
        lambda text: text.replace("Found 2 issue(s) to address:", "Found 2 issue(s) to address:\nFound 2 issue(s) to address:"),
        lambda text: text.replace("✓ HTTPX", "✓ HTTPX\n✓ HTTPX"),
        lambda text: text.replace("✓ PyYAML", ""),
        lambda text: text.replace("1. Run", "3. Extra\n1. Run"),
        lambda text: text.replace("Tip: run", "Traceback: truncated\nTip: run"),
        lambda text: text.replace(
            "⚠ Config version outdated (v0 → v40) (new settings available)",
            "⚠ Config version outdated (v0 → v40) (new settings available)\n"
            "⚠ Config version outdated (v0 → v40) (new settings available)",
        ),
        lambda text: text.replace("✗ Marcel", "Exception: bad\n✗ Marcel"),
        lambda text: text[:-10],
    ],
)
def test_doctor_validator_rejects_adversarial_mutations(pristine_doctor_output, mutation):
    with pytest.raises(ValueError):
        validate_doctor.validate(mutation(pristine_doctor_output), 0)