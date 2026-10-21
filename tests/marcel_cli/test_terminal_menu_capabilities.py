"""Capability guards and real PTY password -> model regressions (no network or credentials)."""

import os
import sys
from types import SimpleNamespace

import pytest

from marcel_cli import curses_ui, terminal_menu


@pytest.mark.parametrize("term", ["", "dumb", "unknown", "not-a-real-terminal"])
def test_limited_term_uses_numbered_menu(monkeypatch, term):
    monkeypatch.setenv("TERM", term)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "2")
    assert curses_ui.curses_radiolist("Model", ["first", "second"]) == 1


@pytest.mark.parametrize("missing", ["cup", "clear", "el", None])
def test_probe_requires_real_screen_operations(monkeypatch, missing):
    fake = SimpleNamespace(
        setupterm=lambda **_: None,
        tigetstr=lambda name: None if name == missing else b"capability",
    )
    monkeypatch.setitem(sys.modules, "curses", fake)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(isatty=lambda: True, fileno=lambda: 1))
    monkeypatch.setattr(os, "get_terminal_size", lambda _: os.terminal_size((80, 24)))
    assert terminal_menu.supports_curses_menu() is (missing is None)


def test_redirected_output_and_small_terminal_are_not_full_screen(monkeypatch):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(isatty=lambda: False))
    assert terminal_menu.supports_curses_menu() is False
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(isatty=lambda: True, fileno=lambda: 1))
    monkeypatch.setitem(sys.modules, "curses", SimpleNamespace(
        setupterm=lambda **_: None, tigetstr=lambda _: b"capability"))
    monkeypatch.setattr(os, "get_terminal_size", lambda _: os.terminal_size((80, 4)))
    assert terminal_menu.supports_curses_menu() is False


@pytest.mark.parametrize(
    "chars, expected",
    [("12\b3\n", "13"), ("12\x152\n", "2"), ("\x1b[D", None), ("\x1bOD", None),
     ("\x1b[A2\n", "2"), ("\x1b[13u", ""), ("\x1b[13;1:3u2\n", "2")],
)
def test_native_numbered_editing_and_navigation(chars, expected, monkeypatch):
    iterator = iter(chars)
    monkeypatch.setattr("marcel_cli.secret_prompt._write", lambda _: None)
    assert terminal_menu._collect_numbered_line(
        lambda timeout=None: next(iterator, ""), "Choice: ", True) == expected


@pytest.mark.parametrize("chars", [
    "\x1b", "\x03", "\x1b[27u", "\x1b[99;5u", "\x1b[27;5;99~"])
def test_native_numbered_cancel(chars, monkeypatch):
    iterator = iter(chars)
    monkeypatch.setattr("marcel_cli.secret_prompt._write", lambda _: None)
    with pytest.raises(KeyboardInterrupt):
        terminal_menu._collect_numbered_line(
            lambda timeout=None: next(iterator, ""), "Choice: ", True)


def test_fallback_checklist_preserves_toggles_and_initial_selection(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(curses_ui, "supports_curses_menu", lambda: False)
    responses = iter(["2", "1", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    selected = {0}
    assert curses_ui.curses_checklist("Workers", ["first", "second"], selected) == {1}
    assert selected == {0}


def test_fallback_single_select_and_default_choice(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(curses_ui, "supports_curses_menu", lambda: False)
    responses = iter(["", "2", "3"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    assert curses_ui.curses_radiolist("Model", ["first", "second"], selected=1) == 1
    assert curses_ui.curses_single_select("Model", ["first", "second"]) == 1
    assert curses_ui.curses_single_select("Model", ["first", "second"]) is None


# Run in isolated child processes: ncurses caches its terminfo initialization process-wide.
PTY_SCRIPT = """
import json, sys, termios
from marcel_cli import setup, curses_ui
from marcel_cli.terminal_menu import supports_curses_menu
attrs = termios.tcgetattr(0)
backend = 'curses' if supports_curses_menu() else 'numbered'
assert setup.prompt('Fake key', password=True) == 'fake-key'
assert termios.tcgetattr(0) == attrs, 'password left terminal raw'
models = [f'model-{i:02}' for i in range(57)]
with setup._setup_navigation_scope():
    setup._SETUP_NAVIGATION.get().reset(section_index=0)
    first = setup.prompt_choice('Choose model', models, default=3)
    try:
        second = setup.prompt_choice('Choose worker', models, default=first)
        result = ('selected', first, second)
    except setup._SetupGoBack as back:
        result = ('back', first, back.prompt_index)
    except setup._SetupCancelled:
        result = ('cancel', first)
assert termios.tcgetattr(0) == attrs, 'menu left terminal raw'
print('RESULT=' + json.dumps([backend, result]), flush=True)
"""


@pytest.mark.skipif(os.name != "posix", reason="real POSIX PTY qualification")
@pytest.mark.parametrize(
    "term, dimensions, backend",
    [("xterm-256color", (24, 100), "curses"), ("dumb", (24, 100), "numbered"),
     ("not-a-real-terminal", (24, 100), "numbered"), ("xterm-256color", (4, 100), "numbered")],
)
@pytest.mark.parametrize("action", ["select", "back", "escape", "interrupt"])
def test_password_then_model_in_real_terminal(tmp_path, term, dimensions, backend, action):
    import json
    pexpect = pytest.importorskip("pexpect")

    # A strict allow-list: the child cannot inherit provider, GitHub or other workspace secrets.
    env = {key: os.environ[key] for key in ("PATH", "PYTHONPATH", "LANG") if key in os.environ}
    env.update(TERM=term, NO_COLOR="1", MARCEL_HOME=str(tmp_path))
    child = pexpect.spawn(sys.executable, ["-c", PTY_SCRIPT], env=env,
                          encoding="utf-8", timeout=12, dimensions=dimensions)
    transcript = []
    try:
        child.expect("Fake key: ")
        transcript.append(child.before + child.after)
        child.send("fake-x\x7fkey\r")
        child.expect("Choose model")
        transcript.append(child.before + child.after)
        if backend == "numbered":
            child.expect(r"Choice \[default")
            child.send("57\r")
        else:
            child.expect("model-")
            child.send("kkkk\r")  # 3 -> 2 -> 1 -> 0 -> 56, exercising cursor wrap
        child.expect("Choose worker")
        transcript.append(child.before + child.after)
        if backend == "numbered":
            child.expect(r"Choice \[default")
        else:
            child.expect("model-")
        if action == "select":
            child.send("\r")  # default = prior selected original index
        elif action == "back":
            child.send("\x1b[D")
        elif action == "escape":
            child.send("\x1b")
        else:
            child.send("\x03")
        child.expect(r"RESULT=([^\r\n]+)")
        result = json.loads(child.match.group(1))
        transcript.append(child.before + child.after)
        expected = ("selected", 56, 56) if action == "select" else (
            ("back", 56, 1) if action == "back" else ("cancel", 56))
        assert result == [backend, list(expected)]
        child.expect(pexpect.EOF)
        child.close()
        assert child.exitstatus == 0
        assert "fake-key" not in "".join(transcript)
        assert "********" in "".join(transcript).replace("\b \b", "")
        if term == "dumb":
            assert "\x1b[" not in "".join(transcript)
    finally:
        child.close(force=True)
