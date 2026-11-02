"""Private, recoverable snapshots and localized context-recovery notices."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from uuid import uuid4


def recovery_language(messages):
    for row in reversed(messages or []):
        if not isinstance(row, dict) or row.get("role") != "user":
            continue
        text = row.get("content")
        if not isinstance(text, str):
            continue
        if re.search(r"\b(ciao|puoi|riesci|vorrei|fammi|mandarmi|immagine|subagenti|grazie|questo)\b", text, re.I):
            return "it"
        if re.search(r"\b(hello|please|could|you|thanks)\b", text, re.I):
            return "en"
    return "en"


def recovery_notice(messages, kind="payload"):
    italian = recovery_language(messages) == "it"
    if kind == "cooldown":
        return (
            "La compressione non è riuscita e il nuovo tentativo è temporaneamente sospeso. "
            "La sessione è conservata. Puoi usare /compress per riprovare ora."
            if italian else
            "Compression failed and a retry is temporarily paused. The session is preserved. "
            "Use /compress to retry now."
        )
    if kind == "payload":
        return (
            "Il corpo della richiesta HTTP è troppo grande (413). Non è una prova del superamento "
            "del contesto del modello. La sessione non viene azzerata; usa /compress per riprovare."
            if italian else
            "The HTTP request body is too large (413); this does not establish a model context overflow. "
            "The session will not be reset. Use /compress to retry."
        )
    return (
        "Recupero della compressione non riuscito. La sessione non viene azzerata. Usa /compress "
        "per riprovare; /new avvia una nuova conversazione solo se lo scegli."
        if italian else
        "Compression recovery failed. The session will not be reset. Use /compress to retry; "
        "/new starts a fresh conversation only if you choose it."
    )


def save_recovery_snapshot(session_id, messages, *, pending_request=None, reason="compression_failure"):
    from marcel_cli.config import get_marcel_home
    directory = Path(get_marcel_home()) / "recovery" / "context"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{uuid4().hex}.json"
    record = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id, "reason": reason, "messages": messages,
        "pending_request": pending_request,
    }
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path.name
