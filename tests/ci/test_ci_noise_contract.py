"""Contracts for the CI-noise reduction workflows and Dependabot policy."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _yaml(path: str) -> dict:
    yaml = pytest.importorskip("yaml")
    # BaseLoader avoids PyYAML's YAML 1.1 conversion of the ``on`` key to
    # ``True`` while still checking that the workflow is parseable.
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_review_comment_is_one_cancelable_poller_per_pr():
    workflow = _yaml(".github/workflows/ci-review-comment.yml")
    trigger = workflow["on"]["workflow_run"]
    comment = workflow["jobs"]["comment"]
    group = workflow["concurrency"]["group"]

    assert trigger["workflows"] == ["CI"]
    assert trigger["types"] == ["in_progress"]
    assert "pull_requests[0].number" in group
    assert workflow["concurrency"]["cancel-in-progress"] == "true"

    # workflow_run remains the trigger (rather than an invalid event filter);
    # the job-level guard prevents push, schedule, and other non-PR CI runs
    # from allocating a runner or posting a comment.
    assert "github.event.workflow_run.event == 'pull_request'" in comment["if"]
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in comment["if"]


def test_publish_evidence_filters_cancelled_runs_before_artifact_work():
    workflow = _yaml(".github/workflows/publish-e2e-evidence.yml")
    trigger = workflow["on"]["workflow_run"]
    publish = workflow["jobs"]["publish"]
    steps = publish["steps"]
    script = (ROOT / ".github/workflows/publish-e2e-evidence.yml").read_text(
        encoding="utf-8"
    )

    assert trigger["workflows"] == ["CI"]
    assert trigger["types"] == ["completed"]
    assert "github.event.workflow_run.event == 'pull_request'" in publish["if"]
    assert "github.event.workflow_run.conclusion != 'cancelled'" in publish["if"]
    assert steps[0]["name"] == "Check out trusted publisher"
    assert "SOURCE_RUN_ID" in script

    # The exact-head/open-PR guard must remain ahead of artifact lookup and
    # download; it prevents stale or closed PR runs from publishing evidence.
    assert '-f head="$HEAD_OWNER:$HEAD_BRANCH" -f state=open' in script
    assert '.head.sha == $ENV.HEAD_SHA' in script
    assert script.index("No open pull request has head") < script.index("ARTIFACT_NAME=")


def test_dependabot_groups_routine_action_updates_without_disabling_security():
    config = _yaml(".github/dependabot.yml")
    update = config["updates"][0]
    text = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    group = update["groups"]["actions-minor-patch"]

    assert update["package-ecosystem"] == "github-actions"
    assert update["open-pull-requests-limit"] == "2"
    assert group["update-types"] == ["minor", "patch"]
    assert "Security updates still open individually and bypass grouping." in text
    assert "ignore:" not in text