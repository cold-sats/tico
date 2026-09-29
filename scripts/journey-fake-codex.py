#!/usr/bin/env python3
"""A stand-in for the `codex` CLI, for scripts/journey-test.sh only: `--version`, `login status`, and `app-server` speaking the small
part of the JSON-RPC protocol the runner's Codex host uses. Every turn is answered with "journey-reply: <prompt>"."""
import json
import sys


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main():
    if "--version" in sys.argv:
        print("codex-cli 99.0.0")
        return
    if sys.argv[1:3] == ["login", "status"]:
        print("Logged in using an API key")
        return
    threads, turns = 0, 0
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, params, rid = msg.get("method"), msg.get("params") or {}, msg.get("id")
        if rid is None:
            continue
        if method in ("thread/start", "thread/resume", "thread/fork"):
            threads += 1
            send({"id": rid, "result": {"thread": {"id": params.get("threadId") or "journey-thread-%d" % threads}}})
        elif method == "turn/start":
            turns += 1
            thread, turn = params["threadId"], "journey-turn-%d" % turns
            text = " ".join(part.get("text", "") for part in params.get("input", []))
            reply = "journey-reply: " + text[:200]
            send({"id": rid, "result": {"turn": {"id": turn}}})
            send({"method": "turn/started", "params": {"threadId": thread, "turn": {"id": turn}}})
            send({"method": "item/agentMessage/delta", "params": {"threadId": thread, "turnId": turn, "delta": reply}})
            send({"method": "item/completed", "params": {"threadId": thread, "turnId": turn,
                  "item": {"type": "agentMessage", "id": "m%d" % turns, "text": reply, "phase": "final_answer"}}})
            send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": turn, "status": "completed"}}})
        else:
            send({"id": rid, "result": {}})


if __name__ == "__main__":
    main()
