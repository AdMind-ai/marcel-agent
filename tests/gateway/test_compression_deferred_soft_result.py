"""Gateway must treat ``compression_deferred`` as a soft result (#49874).

A lock-contended compression defer means a CONCURRENT compressor is actively
shrinking the session. Deferred turns and failed compression must both preserve
the session; neither condition authorizes an implicit reset.

AST invariants on ``gateway/run.py`` (mirrors
``test_35809_auto_reset_clean_context.py``'s load-bearing pin style):

* the ``compression_deferred`` branch precedes non-destructive failure recovery;
* the deferred branch itself performs NO session mutation (no
  ``reset_session``, no ``_evict_cached_agent``, no
  ``_clear_conversation_scope``).
"""

from __future__ import annotations

import ast
import inspect

from gateway import run_turn as gateway_run_turn


def _calls(node: ast.AST) -> set[str]:
    return {
        n.func.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }


def _find_deferred_guarded_preservation_chain() -> ast.If:
    """Find the soft-defer branch before failed-compression preservation."""
    tree = ast.parse(inspect.getsource(gateway_run_turn))

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_consts = [
            n.value
            for n in ast.walk(node.test)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        if "compression_deferred" not in test_consts:
            continue
        if any(isinstance(sub, ast.Constant) and sub.value == "compression_exhausted"
               for branch in node.orelse for sub in ast.walk(branch)):
            return node
    raise AssertionError(
        "Could not locate the compression_deferred guard in front of the "
        "compression-exhausted preservation block in gateway/run_turn.py. The "
        "soft-defer contract (#49874: lock-contended defer must never "
        "auto-reset the session) is no longer structurally guaranteed."
    )


class TestCompressionDeferredIsSoft:
    def test_deferred_branch_preserves_session_without_reset(self):
        """Neither soft defer nor failed compression may reset or evict the session."""
        node = _find_deferred_guarded_preservation_chain()
        body_calls = set()
        for sub in node.body:
            body_calls |= _calls(sub)
        forbidden = {
            "reset_session",
            "_evict_cached_agent",
            "_clear_conversation_scope",
        }
        assert not (_calls(node) & forbidden), "Compression recovery must never reset or evict the session."
        assert not (body_calls & forbidden), (
            f"The compression_deferred branch in gateway/run.py performs "
            f"session mutation ({body_calls & forbidden}). A lock-contended "
            f"defer is transient — the session must stay intact so the next "
            f"message retries against the freshly compressed context "
            f"(#49874, #69870)."
        )

