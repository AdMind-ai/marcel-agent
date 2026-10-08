#!/usr/bin/env python3
"""Qualify public release assets using a real Ubuntu install and real Router.

No fixture Router or patched prompt functions are used. The driver answers the
product's numbered terminal UI through a PTY. Only allowlisted evidence is kept;
the disposable HOME, configuration, credentials and sessions are removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import urllib.request

import pexpect
import yaml


ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07)")
PRIMARY = "openai/gpt-4.1-nano"
BACKUPS = ["openai/gpt-4o-mini", "openai/gpt-4.1-mini"]
ROUTER = "https://marcel-agent.com/api/v1"


def request_json(url: str, key: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return json.load(response)


def public_assets(tag: str, root: Path) -> Path:
    release = request_json(f"https://api.github.com/repos/AdMind-ai/marcel-agent/releases/tags/{tag}")
    assert release["prerelease"] and not release["draft"]
    expected = {"install.sh", "install.ps1", "install.cmd", f"marcel-agent-{tag}.tar.gz", "SHA256SUMS"}
    assert {item["name"] for item in release["assets"]} == expected
    for item in release["assets"]:
        with urllib.request.urlopen(item["browser_download_url"], timeout=120) as source:
            with (root / item["name"]).open("wb") as destination:
                shutil.copyfileobj(source, destination)
    manifest = [
        line.split("  ", 1)
        for line in (root / "SHA256SUMS").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert len(manifest) == 4 and {name for _, name in manifest} == expected - {"SHA256SUMS"}
    for digest, name in manifest:
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    with tarfile.open(root / f"marcel-agent-{tag}.tar.gz") as archive:
        assert archive.getmembers()
    return root / "install.sh"


def menu_items(screen: str) -> list[tuple[int, str, bool]]:
    return [
        (int(match[1]), match[2], "✓" in match[0])
        for match in re.finditer(r"(?m)^\s*(?:\([^\n]*?\)|\[[^\n]*?\])\s*(\d+)\.\s*(.+)$", screen)
    ]


def choose_matching(items: list, text: str) -> str:
    for index, label, _ in items:
        if text.casefold() in label.casefold():
            return str(index)
    raise AssertionError(f"Required menu item absent: {text}")


def drive(command: list[str], env: dict, *, workers: bool, key: str, image_key: str,
          keep_main_order: list[str] | None = None) -> dict:
    child = pexpect.spawn(command[0], command[1:], env=env, encoding="utf-8",
                          timeout=600, echo=False, dimensions=(50, 240),
                          maxread=65536, searchwindowsize=65536)
    # Never attach a logfile: credentials are typed only into the masked UI.
    patterns = [
        r"Choice \[default \d+\]:",
        r"Toggle # \(or Enter to confirm\):",
        r"Agent name(?: \[[^\r\n]*\])?:",
        r"Marcel Router base URL(?: \[[^\r\n]*\])?:",
        r"(?:New )?Marcel Routing API key:",
        r"Fallback order by number \(Enter keeps this order\)(?: \[[^\r\n]*\])?:",
        r"Sub-agent name:",
        r"Maximum API requests per worker run \(blank = no limit\):",
        r"Maximum worker duration in seconds \(blank = no limit\):",
        r"FAL\.ai[^\r\n]* API key:",
        r"[^\r\n]*\[(?:Y/n|y/N)\]:?\s?",
        pexpect.EOF,
    ]
    checklist = ""
    adds = 0
    seen_main = False
    selected_order: list[str] = []
    decisions: list[str] = []
    tail = ""
    pending_screen = ""
    model_kind = "main"
    try:
        for _ in range(180):
            event = child.expect(patterns)
            screen = pending_screen + ANSI.sub("", child.before).replace("\r", "")
            pending_screen = ""
            tail = screen[-1800:].replace(key, "[redacted]")
            if image_key:
                tail = tail.replace(image_key, "[redacted]")
            seen_main = seen_main or "Main agent configured:" in screen
            if event == 11:
                child.close()
                assert child.exitstatus == 0, f"Command exited with status {child.exitstatus}"
                assert seen_main, "Normal wizard did not reach the main-agent summary"
                return {"main_summary_seen": True, "decisions": decisions, "selected_order": selected_order}
            child.timeout = 90
            answer = ""
            if event == 0:
                checklist = ""
                items = menu_items(screen)
                assert items, "Numbered UI did not expose menu items"
                title = next((line.strip() for line in screen.splitlines()
                              if line.strip() and "Select by number" not in line
                              and not re.match(r"^\s*\([●○]\)", line)), "radio")
                print("Wizard menu:", title[-180:], flush=True)
                if "Orchestrator model" in screen or "Sub-agent model for" in screen:
                    model_kind = "worker" if "Sub-agent model for" in screen else "main"
                    answer = choose_matching(items, f"[{PRIMARY}]")
                elif "Connection" in screen and any("Marcel Router" in label for _, label, _ in items):
                    answer = choose_matching(items, "Marcel Router")
                elif "Sub-agent configuration" in screen:
                    answer = choose_matching(items, "Configure manually")
                elif "Sub-agent activity" in screen:
                    answer = choose_matching(items, "Image generation")
                elif "Add a sub-agent?" in screen:
                    assert seen_main, "Workers prompted before main summary"
                    answer = choose_matching(items, "Yes" if workers and adds == 0 else "No")
                    adds += 1
                elif "Sub-agent permissions" in screen:
                    answer = choose_matching(items, "Only the selected tools")
                elif any(title in screen for title in (
                    "Add Google Workspace?", "Add an email account?", "Connect Telegram",
                    "Set token or estimated cost limits", "Enable memory maintenance?",
                )):
                    answer = choose_matching(items, "No")
                elif "Retry Marcel Router connection?" in screen:
                    raise AssertionError("Real Router discovery failed in normal setup")
                elif any("Edge TTS" in label for _, label, _ in items):
                    answer = choose_matching(items, "Edge")
                decisions.append("radio:" + (answer or "default"))
            elif event == 1:
                if "Choose fallback models" in screen:
                    checklist = "fallback"
                elif "Choose all models Marcel may use" in screen:
                    checklist = "available"
                elif re.search(r"What can this .+ sub-agent do\?", screen):
                    checklist = "tools"
                items = menu_items(screen)
                if checklist == "fallback":
                    desired = set(BACKUPS)
                    for number, label, checked in items:
                        model = label.rsplit("[", 1)[-1].split("]", 1)[0]
                        if checked != (model in desired):
                            answer = str(number)
                            break
                    if not answer:
                        selected_order = [
                            label.rsplit("[", 1)[-1].split("]", 1)[0]
                            for _, label, checked in items if checked
                        ]
                decisions.append("checklist:" + checklist)
            elif event == 2:
                answer = "ReleasePilot"
            elif event == 3:
                answer = ROUTER
            elif event == 4:
                answer = key
            elif event == 5:
                assert set(selected_order) == set(BACKUPS)
                if model_kind == "main" and keep_main_order is not None:
                    selected_order = list(keep_main_order)
                else:
                    answer = "2,1"
                    selected_order.reverse()
            elif event == 6:
                answer = "ImagePilot"
            elif event == 7:
                answer = "3"
            elif event == 8:
                answer = "90"
            elif event == 9:
                answer = image_key
            elif event == 10:
                prompt = ANSI.sub("", child.after)
                if "Add a sub-agent?" in prompt:
                    assert seen_main
                    answer = "y" if workers and adds == 0 else "n"
                    adds += 1
                else:
                    answer = "n"
            child.sendline(answer)
            # prompt_toolkit redraws the submitted prompt before its newline.
            # Drain that line so it cannot be mistaken for the next question.
            child.expect([r"\r?\n", pexpect.EOF], timeout=15)
            pending_screen = ANSI.sub("", child.before or "").replace("\r", "") + "\n"
            seen_main = seen_main or "Main agent configured:" in (child.before or "")
        raise AssertionError("Too many wizard prompts")
    except Exception as exc:
        # Retain only the sanitized tail for diagnosing a UI failure.
        screen = ANSI.sub("", child.before or "").replace("\r", "")
        screen = "\n".join(line.rstrip() for line in screen.splitlines() if line.strip())
        screen = screen[-2400:].replace(key, "[redacted]")
        if image_key:
            screen = screen.replace(image_key, "[redacted]")
        reason = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
        print("Wizard failure:", reason.replace(key, "[redacted]"), flush=True)
        print("Sanitized last screen:", screen or tail, flush=True)
        raise RuntimeError("Terminal driver failed: " + type(exc).__name__) from None
    finally:
        if child.isalive():
            child.terminate(force=True)


def installed_config(python: Path, install: Path, env: dict) -> dict:
    result = subprocess.run(
        [str(python), "-c", "import json; from marcel_cli.config import load_config; print(json.dumps(load_config()))"],
        cwd=install, env=env, capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)

def successful_worker_result(payload: dict) -> bool:
    """Require a runtime result with real model consumption, never echoed text."""
    return isinstance(payload, dict) and not payload.get("error") and any(
        isinstance(item, dict)
        and item.get("status") in {"completed", "success"}
        and not item.get("error")
        and item.get("api_calls", 0) > 0
        and item.get("model") == PRIMARY
        and "WORKER_ROUTER_PILOT_OK" in str(item.get("summary", ""))
        for item in payload.get("results", [])
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.21.0-rc.5")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ["MARCEL_ROUTER_TEST_KEY"]
    image_key = os.environ.get("MARCEL_IMAGE_TEST_KEY", "")
    tag_object = request_json(
        f"https://api.github.com/repos/AdMind-ai/marcel-agent/git/ref/tags/{args.tag}")["object"]
    if tag_object["type"] == "tag":
        tag_object = request_json(
            f"https://api.github.com/repos/AdMind-ai/marcel-agent/git/tags/{tag_object['sha']}")["object"]
    assert tag_object["type"] == "commit"
    expected_sha = tag_object["sha"]
    evidence = {"tag": args.tag, "candidate_sha": expected_sha,
                "simulated": False, "image_generation": "not exercised"}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="marcel-public-pilot-") as disposable:
        root = Path(disposable)
        home = root / "home"
        home.mkdir()
        assets = root / "assets"
        assets.mkdir()
        env = {name: value for name, value in os.environ.items()
               if not any(part in name.upper() for part in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "TEST_KEY", "GITHUB", "ACTIONS", "RUNNER"))}
        # TERM=dumb can enter curses after masked input yet cannot draw the
        # model picker. An absent terminfo entry consistently selects the
        # product's native numbered fallback, without monkeypatching its UI.
        env.update(HOME=str(home), MARCEL_HOME=str(home / ".marcel"),
                   TERM="marcel-qualification-numbered",
                   PATH=f"{home}/.local/bin:" + os.environ["PATH"],
                   PYTHONUNBUFFERED="1", UV_NO_PROGRESS="1")
        env.pop("MARCEL_NONINTERACTIVE", None)
        env.pop("UV_PROJECT_ENVIRONMENT", None)
        if image_key:
            # Installation-local opt-in image credential, not a maintainer key.
            env["FAL_KEY"] = image_key
        try:
            installer = public_assets(args.tag, assets)
            evidence["public_asset_checksums"] = "passed"
            models = request_json(ROUTER + "/models", key)["data"]
            ids = {entry["id"] for entry in models}
            assert {PRIMARY, *BACKUPS} <= ids, "Required inexpensive test models absent from account catalog"
            evidence["account_model_count"] = len(models)
            print("Public assets verified; authenticated account catalog:", len(models), flush=True)
            print("Starting the normal public installer; dependency progress animation disabled.", flush=True)
            evidence["main_ui"] = drive(["bash", str(installer), "--branch", args.tag],
                                        env, workers=False, key=key, image_key=image_key)
            assert len(evidence["main_ui"]["selected_order"]) == 2
            assert set(evidence["main_ui"]["selected_order"]) == set(BACKUPS)
            install = home / ".marcel" / "marcel-agent"
            python = install / "venv" / "bin" / "python"
            sha = subprocess.check_output(["git", "-C", str(install), "rev-parse", "HEAD"], env=env, text=True).strip()
            assert sha == expected_sha
            evidence["installed_sha"] = sha
            config = installed_config(python, install, env)
            assert not config["delegation"]["workers"]
            main_order = config["marcel"]["orchestrator"]["fallback_models"]
            assert main_order == evidence["main_ui"]["selected_order"]
            assert [item["model"] for item in config["fallback_providers"]] == main_order
            assert key not in (home / ".marcel" / "config.yaml").read_text()
            evidence["main_saved_and_reloaded"] = "passed"
            print("Normal install and zero-worker configuration reload passed.", flush=True)
            result = subprocess.run(
                [str(python), "-m", "marcel_cli.main", "chat", "-q",
                 "Reply with exactly ROUTER_PILOT_OK. Do not use any tools.", "-t", "none"],
                env=env, cwd=install, capture_output=True, text=True, timeout=180,
            )
            assert result.returncode == 0 and "ROUTER_PILOT_OK" in result.stdout, "Installed main runtime did not produce the live test response"
            evidence["main_live_response"] = "passed"
            print("Installed main real Router response passed.", flush=True)
            for backup in BACKUPS:
                result = subprocess.run(
                    [str(python), str(install / "marcel"), "chat", "-q",
                     "Reply with exactly FALLBACK_MODEL_PILOT_OK. Do not use tools.",
                     "-t", "none", "-m", backup],
                    env=env, cwd=install, capture_output=True, text=True, timeout=180,
                )
                assert result.returncode == 0 and "FALLBACK_MODEL_PILOT_OK" in result.stdout, \
                    "A selected fallback did not execute through the real Router"
            evidence["fallback_models_live_responses"] = "passed"
            evidence["worker_ui"] = drive(
                [str(python), "-m", "marcel_cli.main", "setup", "marcel"],
                env, workers=True, key=key, image_key=image_key, keep_main_order=main_order,
            )
            config = installed_config(python, install, env)
            worker = config["delegation"]["workers"]["imagepilot"]
            assert worker["model"] == PRIMARY and worker["provider"] == "marcel"
            assert worker["image_service"] == "global" and "image_gen" in worker["toolsets"]
            assert worker["permissions"] == "selected"
            assert worker["fallback_models"] == evidence["worker_ui"]["selected_order"]
            assert worker["budget"]["max_requests"] == 3
            assert key not in (home / ".marcel" / "config.yaml").read_text()
            assert main_order == config["marcel"]["orchestrator"]["fallback_models"]
            evidence["worker_saved_and_reloaded"] = "passed"
            result = subprocess.run(
                [str(python), str(install / "marcel"), "chat", "-q",
                 "Use delegate_task with worker imagepilot. Its goal is to reply exactly "
                 "WORKER_ROUTER_PILOT_OK without creating an image or using tools. "
                 "Wait for that worker and relay its response.", "-t", "delegation"],
                env=env, cwd=install, capture_output=True, text=True, timeout=240,
            )
            assert result.returncode == 0, "Installed main with worker exited unsuccessfully"
            with sqlite3.connect(home / ".marcel" / "state.db") as db:
                messages = db.execute(
                    "SELECT session_id, role, content, tool_calls, tool_call_id FROM messages ORDER BY rowid"
                ).fetchall()
            delegated = False
            worker_answer = False
            delegate_calls = 0
            tool_results = 0
            result_errors = 0
            registered_calls: set[tuple[str, str]] = set()
            dispatched: dict[str, str] = {}
            async_completed = 0
            failure_signals: set[str] = set()
            signal_patterns = {
                "credentials": r"api.?key|credential|unauthorized|authentication",
                "provider": r"provider|base.?url",
                "budget": r"budget|request.?limit|time.?limit",
                "timeout": r"timeout|timed out",
                "approval": r"approval|permission|denied",
                "model": r"model|not.?found",
            }
            for session_id, role, content, calls, tool_call_id in messages:
                for call in json.loads(calls or "[]"):
                    function = call.get("function", {})
                    if function.get("name") != "delegate_task":
                        continue
                    delegate_calls += 1
                    raw_arguments = function.get("arguments") or "{}"
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                    named_worker = arguments.get("worker") == "imagepilot" or any(
                        task.get("worker") == "imagepilot"
                        for task in arguments.get("tasks", []) if isinstance(task, dict)
                    )
                    delegated |= named_worker
                    if named_worker and call.get("id"):
                        registered_calls.add((session_id, call["id"]))
                if role == "tool" and content:
                    tool_results += 1
                    try:
                        payload = json.loads(content)
                    except (TypeError, ValueError):
                        continue
                    if (session_id, tool_call_id) not in registered_calls:
                        continue
                    if isinstance(payload, dict) and payload.get("status") == "dispatched" and payload.get("delegation_id"):
                        dispatched[payload["delegation_id"]] = session_id
                    items = payload.get("results", []) if isinstance(payload, dict) else []
                    for item in [payload, *items]:
                        if not isinstance(item, dict) or not item.get("error"):
                            continue
                        result_errors += 1
                        for name, pattern in signal_patterns.items():
                            if re.search(pattern, str(item["error"]), re.I):
                                failure_signals.add(name)
                    worker_answer |= successful_worker_result(payload)
            # Background delegation returns a dispatch handle as the tool
            # result; its actual completion is persisted in the runtime ledger.
            # Bind that completion to the named call and originating session.
            with sqlite3.connect(home / ".marcel" / "state.db") as db:
                for delegation_id, parent_session in dispatched.items():
                    row = db.execute(
                        "SELECT state, parent_session_id, result_json FROM async_delegations WHERE delegation_id = ?",
                        (delegation_id,),
                    ).fetchone()
                    if row and row[0] == "completed" and row[1] == parent_session:
                        async_completed += 1
                        worker_answer |= successful_worker_result(json.loads(row[2] or "{}"))
            # Metadata and fixed diagnostic categories only; no transcripts or
            # arbitrary provider error text may enter retained evidence.
            evidence["delegation_diagnostics"] = {
                "registered_worker_requested": delegated,
                "successful_worker_result": worker_answer,
                "delegate_call_count": delegate_calls,
                "tool_result_count": tool_results,
                "result_error_count": result_errors,
                "async_dispatch_count": len(dispatched),
                "async_completed_count": async_completed,
                "failure_signals": sorted(failure_signals),
                "message_count": len(messages),
                "main_output_has_worker_marker": "WORKER_ROUTER_PILOT_OK" in result.stdout,
            }
            assert delegated and worker_answer, "Real registered image worker was not executed successfully"
            evidence["main_with_worker_live_delegation"] = "passed"
            print("Installed main delegated to the registered image worker over the real Router.", flush=True)
            evidence["worker"] = {field: worker[field] for field in (
                "model", "provider", "activity", "fallback_models", "toolsets",
                "permissions", "budget", "image_service", "max_concurrency",
            )}
            evidence["fallbacks"] = {"selected_and_reloaded": main_order,
                                     "failure_execution": "not injected; no simulated outages"}
            evidence["image_service"] = {
                "configured": bool(config.get("image_gen")),
                "reason": "test credential supplied" if image_key else "separate image-service test credential not supplied",
            }
            evidence["status"] = "passed"
        except Exception as exc:
            evidence["status"] = "failed"
            evidence["failure_type"] = type(exc).__name__
            raise
        finally:
            args.evidence.write_text(json.dumps(evidence, indent=2) + "\n")
    print("Public Ubuntu / real Router pilot passed; disposable runtime removed.")


if __name__ == "__main__":
    main()
