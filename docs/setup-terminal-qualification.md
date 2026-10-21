# Setup terminal qualification

Local qualification on 2026-10-12. No provider credentials, Router requests, release
publication or suspended Ubuntu qualification jobs were used.

## Public baseline comparison

Compared the public `v0.21.0-rc.5` sources from
`https://github.com/AdMind-ai/marcel-agent` with the working checkout:

- `marcel_cli/curses_ui.py` and `marcel_cli/secret_prompt.py` were identical
  before this change.
- `marcel_cli/setup.py` differed in banner/onboarding copy, not in the masked
  prompt or menu navigation primitives.
- Password entry restores terminal attributes in a `finally` block. The menu
  previously checked only stdin's TTY status and relied on `curses.error` to
  select its numbered fallback. Its scoped fallback still used prompt_toolkit.

The baseline PTY run in this environment completed on both xterm and dumb.
It did **not** reproduce the pilot's blank screen here: dumb fell through a
curses initialization error to numbered input. It nevertheless emitted cursor
control sequences on dumb. This is environment-dependent evidence, not a
claim that rc.5's documented pilot failure did not occur.

## Behavior

The menu now checks input and output TTYs, TERM, terminfo cursor addressing,
clear-screen/erase-line operations, and actual terminal dimensions before
entering curses. Missing terminfo, dumb/unknown/unset TERM, redirected output,
or insufficient dimensions select numbered input. A screen that shrinks
below the menu's row/column requirements also falls back instead of waiting
for input on a screen without visible choices.

Scoped numbered setup input on limited terminals uses native character reads,
not a full-screen or cursor-addressing renderer. It supports:

- numbers, Enter/default, backspace and Ctrl+U;
- Escape/Ctrl+C cancellation and Left backtracking when enabled;
- CSI/SS3 Left and enhanced CSI-u/modifyOtherKeys control keys;
- terminal restoration on normal completion, cancellation, EOF and back.

Single-select, radio and checklist fallbacks retain original indices, defaults
and selections. Existing setup section/prompt replay and scoped cancellation
remain unchanged; this does not add an all-or-nothing configuration transaction
or change when the setup saves credentials.

## Verification

`tests/marcel_cli/test_terminal_menu_capabilities.py` runs the real
`setup.prompt(password=True)` and model/worker menu primitives in child PTYs,
using a fictitious key and an offline 57-model list. Child environments use a
strict allow-list and an isolated `MARCEL_HOME`.

Sixteen PTY cases cover:

| Terminal | Renderer | Actions after masked password and model selection |
| --- | --- | --- |
| xterm-256color, 24×100 | curses | confirm default, Left, Escape, Ctrl+C |
| dumb, 24×100 | native numbered | confirm default, Left, Escape, Ctrl+C |
| absent terminfo, 24×100 | native numbered | confirm default, Left, Escape, Ctrl+C |
| xterm-256color, 4×100 | native numbered | confirm default, Left, Escape, Ctrl+C |

Assertions check selection of the last original model index, masked output,
no cursor-control sequences on dumb, backtracking/cancellation signals and
terminal attribute restoration. Unit tests also exercise capability probing,
number editing, enhanced keys, default selection and checklist toggles.

The focused run passed **127 tests**, including the existing secret capture,
setup navigation/replay, Marcel configuration and curses rendering suites.
The PTY library reported a Python fork-with-threads deprecation warning; no
test failed or was counted as a live Router qualification.

Run the focused suite in an environment with pytest, pexpect and Marcel's
normal runtime dependencies:

```sh
python -m pytest -q --override-ini addopts='' \
  tests/marcel_cli/test_terminal_menu_capabilities.py \
  tests/marcel_cli/test_secret_prompt.py \
  tests/marcel_cli/test_setup_prompt_menus.py \
  tests/marcel_cli/test_curses_arrow_keys.py \
  tests/marcel_cli/test_curses_radiolist_viewport.py \
  tests/marcel_cli/test_curses_ui_search.py \
  tests/marcel_cli/test_curses_ui_fuzzy_rank.py \
  tests/marcel_cli/test_terminal_menu_fallbacks.py \
  tests/marcel_cli/test_setup_marcel.py \
  tests/marcel_cli/test_setup_marcel_script.py \
  tests/marcel_cli/test_prompt_api_key.py \
  tests/cli/test_cli_secret_capture.py
```

Real native Windows consoles and SSH/tmux transport timing were not qualified
by these local Linux PTYs.
