"""Deterministic stdio peers for transport-path budget tests; no provider access."""

import json
from pathlib import Path
import sys
import time

# CodexAppServerClient appends "app-server"; ACP uses the same script directly.
args = [arg for arg in sys.argv[1:] if arg != "app-server"]
scenario, log_path = args[:2]
inp, out = 0, 0


def send(message):
    print(json.dumps(message), flush=True)


def note(method, params):
    send({"method": method, "params": params})


for line in sys.stdin:
    msg = json.loads(line)
    method, params = msg.get("method"), msg.get("params") or {}
    with Path(log_path).open("a") as log:
        log.write(json.dumps(msg) + "\n")
    if scenario == "handshake_stall" and method == "initialize":
        continue  # Still reads interrupt/cancel; never answers initialize.
    result = {}
    if method == "thread/start":
        result = {"thread": {"id": "thread-test"}}
    elif method == "session/new":
        result = {"sessionId": "session-test"}
    elif method == "turn/start":
        turn = "turn-test"
        send({"id": msg["id"], "result": {"turn": {"id": turn}}})
        if scenario == "stall":
            continue
        if scenario != "missing":
            # Two internal requests: `last` alone would undercount.
            for increment in (3, 4):
                inp += increment
                out += 1
                total = {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out}
                if scenario == "malformed":
                    total["inputTokens"] = True
                if scenario == "decreasing" and increment == 4:
                    total["inputTokens"] = 1
                note("thread/tokenUsage/updated", {
                    "threadId": "thread-test", "turnId": turn,
                    "tokenUsage": {"total": total, "last": {
                        "inputTokens": increment, "outputTokens": 1,
                    }},
                })
        note("item/completed", {
            "threadId": "thread-test", "turnId": turn,
            "item": {"id": "answer", "type": "agentMessage", "text": "done"},
        })
        note("turn/completed", {"threadId": "thread-test", "turn": {"id": turn, "status": "completed"}})
        continue
    elif method == "session/prompt":
        if scenario == "stall":
            continue
        note("session/update", {
            "sessionId": "session-test",
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "done"}},
        })
        result = {"stopReason": "end_turn"}
        if scenario != "missing":
            result["usage"] = {"inputTokens": 7, "outputTokens": 2, "totalTokens": 9}
            if scenario == "malformed":
                result["usage"]["inputTokens"] = True
    if "id" in msg:
        send({"id": msg["id"], "result": result})
    if scenario == "prompt_unread" and method in {"session/new", "thread/start"}:
        time.sleep(60)  # Never read the large prompt; fill stdin and block the caller's write.
