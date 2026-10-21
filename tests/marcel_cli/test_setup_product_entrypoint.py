"""Simulated routing regressions; these do not replace live installer evidence."""
import argparse
import copy
from pathlib import Path

import pytest


@pytest.mark.parametrize("argv", ["marcel", "/package/marcel_cli/main.py"])
@pytest.mark.parametrize("existing", [False, True])
def test_marcel_setup_never_replaces_router_with_legacy_provider(monkeypatch, tmp_path, argv, existing):
    from marcel_cli import setup
    from marcel_cli import auth

    config = copy.deepcopy(setup.DEFAULT_CONFIG)
    saved, sections = [], []
    monkeypatch.setattr(setup.sys, "argv", [argv, "setup"])
    monkeypatch.setattr(setup, "load_config", lambda: config)
    monkeypatch.setattr(setup, "save_config", lambda value: saved.append(copy.deepcopy(value)))
    monkeypatch.setattr(setup, "ensure_marcel_home", lambda: None)
    monkeypatch.setattr(setup, "get_marcel_home", lambda: tmp_path)
    monkeypatch.setattr(setup, "get_config_path", lambda: tmp_path / "config.yaml")
    monkeypatch.setattr(setup, "_backup_config_file", lambda path: None)
    monkeypatch.setattr(setup, "is_interactive_stdin", lambda: True)
    monkeypatch.setattr(setup, "get_env_value", lambda name: "fake-existing" if existing else "")
    monkeypatch.setattr(auth, "get_active_provider", lambda: None)
    monkeypatch.setattr(setup, "_offer_openclaw_migration", lambda home: False)
    monkeypatch.setattr(setup, "_print_setup_summary", lambda *args: None)

    def forbidden(*args, **kwargs):
        pytest.fail("Marcel normal setup entered a legacy mode/provider picker")

    monkeypatch.setattr(setup, "prompt_choice", forbidden)
    monkeypatch.setattr(setup, "setup_model_provider", forbidden)
    monkeypatch.setattr(setup, "setup_marcel",
                        lambda value: value.update(model={"provider": "marcel", "default": "fixture/chat"}))

    def run_steps(steps):
        for name, run in steps:
            sections.append(name)
            run()

    monkeypatch.setattr(setup, "_run_setup_steps", run_steps)
    setup._run_setup_wizard_impl(argparse.Namespace(section=None, portal=False))
    assert sections == ["Marcel Agent"]
    assert saved[-1]["model"]["provider"] == "marcel"


def test_public_installers_use_the_canonical_product_entrypoint():
    root = Path(__file__).resolve().parents[2]
    shell = (root / "scripts/install.sh").read_text()
    powershell = (root / "scripts/install.ps1").read_text()
    assert '"$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/marcel" setup < /dev/tty' in shell
    assert '& ".\\venv\\Scripts\\python.exe" ".\\marcel" setup' in powershell
    assert "-m marcel_cli.main setup" not in shell
    assert "-m marcel_cli.main setup" not in powershell
