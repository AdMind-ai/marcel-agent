"""Terminal capability checks and line input that needs no screen renderer."""

import os
import sys


def supports_curses_menu() -> bool:
    """Require real input/output TTYs and the terminfo operations menus use.

    Do not cache this decision: streams and terminal dimensions can change between prompts.
    Color and cursor visibility are optional, not prerequisites for a readable menu.
    """
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return False
        term = os.environ.get("TERM", "")
        if not term or term.lower() in {"dumb", "unknown"}:
            return False
        import curses

        fd = sys.stdout.fileno()
        curses.setupterm(term=term, fd=fd)
        if not all(curses.tigetstr(cap) for cap in ("cup", "clear", "el")):
            return False
        size = os.get_terminal_size(fd)
        return size.lines >= 5 and size.columns >= 20
    except (ImportError, OSError, ValueError):
        return False
    except Exception:
        # Some platforms lack curses/terminfo altogether (including native Windows).
        return False


def numbered_line_input(prompt: str, *, allow_back: bool) -> str | None:
    """Read a number without cursor addressing; None means Left/back.

    Escape and Ctrl+C cancel, Ctrl+D/closed input raises EOFError. Terminal attributes
    are restored even when the setup navigation handler exits via BaseException.
    """
    if os.name == "nt":
        import msvcrt

        def read_char(timeout=None):
            if timeout is not None:
                import time
                end = time.monotonic() + timeout
                while not msvcrt.kbhit():
                    if time.monotonic() >= end:
                        return ""
                    time.sleep(0.005)
            ch = msvcrt.getwch()
            if ch in {"\x00", "\xe0"}:
                return "\x1b[D" if msvcrt.getwch() == "K" else "\x00"
            return ch

        return _collect_numbered_line(read_char, prompt, allow_back)

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    attrs = termios.tcgetattr(fd)

    def read_char(timeout=None):
        if timeout is not None and not select.select([fd], [], [], timeout)[0]:
            return ""
        # Read the descriptor, not TextIOWrapper: buffering must not steal the next menu's keys.
        return os.read(fd, 1).decode("ascii", errors="ignore") or "\x04"

    try:
        tty.setraw(fd)
        return _collect_numbered_line(read_char, prompt, allow_back)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)


def _collect_numbered_line(read_char, prompt: str, allow_back: bool) -> str | None:
    from marcel_cli.secret_prompt import _write

    value = []
    _write(prompt)
    while True:
        ch = read_char()
        if ch in {"\r", "\n"}:
            _write("\r\n")
            return "".join(value)
        if ch in {"", "\x04", "\x1a"}:
            _write("\r\n")
            raise EOFError
        if ch == "\x03":
            _write("\r\n")
            raise KeyboardInterrupt
        if ch == "\x1b[D":  # native Windows Left
            if allow_back:
                _write("\r\n")
                return None
            continue
        if ch == "\x1b":
            tail = read_char(0.06)
            if not tail:
                _write("\r\n")
                raise KeyboardInterrupt
            if tail in {"[", "O"}:
                sequence = ""
                for _ in range(32):
                    part = read_char(0.06)
                    if not part:
                        break
                    sequence += part
                    if "@" <= part <= "~":
                        break
                from marcel_cli.curses_ui import (
                    _enhanced_key_action, _parse_csi_numbers, _parse_csi_u_key)
                if sequence.endswith("D") and allow_back:
                    _write("\r\n")
                    return None
                enhanced = _parse_csi_u_key(sequence[:-1]) if sequence.endswith("u") else None
                if sequence.endswith("~"):
                    params = _parse_csi_numbers(sequence[:-1])
                    if len(params) >= 3 and params[0] == 27:
                        enhanced = (params[2], params[1], 1)
                if enhanced and enhanced[2] != 3:
                    action = _enhanced_key_action(enhanced[0], enhanced[1])
                    if action in {"cancel", "interrupt"}:
                        _write("\r\n")
                        raise KeyboardInterrupt
                    if action == "select":
                        _write("\r\n")
                        return "".join(value)
            continue
        if ch in {"\b", "\x7f", "\x15"}:
            count = len(value) if ch == "\x15" else min(1, len(value))
            for _ in range(count):
                value.pop()
                _write("\b \b")
        elif ch.isascii() and ch.isprintable():
            value.append(ch)
            _write(ch)
