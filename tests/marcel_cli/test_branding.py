"""Regression coverage for Marcel's primary installer and setup branding."""

from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from marcel_cli import banner, setup as setup_mod, setup_quick
from marcel_cli.branding import MARCEL_TAGLINE, MARCEL_UPSTREAM_ATTRIBUTION
from marcel_cli.default_soul import is_legacy_template_soul
from marcel_cli.setup_marcel import MARCEL_SOUL_MD, ensure_marcel_soul


def test_cli_banner_uses_admind_product_identity_and_separate_upstream_attribution():
    with (
        patch.object(banner, "get_available_skills", return_value={}),
        patch.object(banner, "get_update_result", return_value=None),
        patch.object(banner, "_mcp_configured", return_value=False),
    ):
        console = Console(record=True, force_terminal=False, color_system=None, width=160)
        banner.build_welcome_banner(
            console=console,
            model="openai/gpt-5",
            cwd="/tmp",
            tools=[],
            enabled_toolsets=[],
            provider="openrouter",
        )

    rendered = console.export_text()
    assert MARCEL_TAGLINE in rendered
    assert MARCEL_UPSTREAM_ATTRIBUTION in rendered
    assert "Nous Portal" not in rendered


def test_quick_setup_has_product_label_and_provider_service_copy():
    assert setup_mod._FIRST_TIME_MODES[0][0] == "Quick setup"
    assert "Nous Portal" in setup_mod._QUICK_SETUP_PROVIDER_COPY
    assert "sign in through Nous Portal" in setup_quick._run_first_time_quick_setup.__doc__


def test_script_installers_keep_upstream_attribution_separate_from_tagline():
    root = Path(__file__).parents[2]
    for relative_path in ("scripts/install.sh", "scripts/install.ps1", "setup-marcel.sh"):
        source = (root / relative_path).read_text(encoding="utf-8")
        assert MARCEL_TAGLINE in source
        assert MARCEL_UPSTREAM_ATTRIBUTION in source
        assert "open source AI agent by Nous Research" not in source


def _seeded_soul_template(relative_path: str, start: str, end: str) -> str:
    source = (Path(__file__).parents[2] / relative_path).read_text(encoding="utf-8")
    return source.split(start, 1)[1].split(end, 1)[0].rstrip("\r\n")


@pytest.mark.parametrize(
    ("name", "relative_path", "start", "end"),
    (
        (
            "POSIX installer",
            "scripts/install.sh",
            "cat > \"$MARCEL_HOME/SOUL.md\" << 'SOUL_EOF'\n",
            "\nSOUL_EOF",
        ),
        (
            "PowerShell installer",
            "scripts/install.ps1",
            '$soulContent = @"\n',
            '\n"@',
        ),
    ),
)
def test_installer_soul_templates_are_safe_for_setup_wizard(
    tmp_path, monkeypatch, name, relative_path, start, end
):
    """Installer-seeded identity is recognized as generated, not user customization."""
    template = _seeded_soul_template(relative_path, start, end)
    assert is_legacy_template_soul(template), name

    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text(template, encoding="utf-8")
    monkeypatch.setattr("marcel_cli.config.get_marcel_home", lambda: tmp_path)

    assert ensure_marcel_soul(), name
    assert soul_path.read_text(encoding="utf-8") == MARCEL_SOUL_MD
