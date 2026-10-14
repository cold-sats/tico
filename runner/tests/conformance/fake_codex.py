"""A stand-in for the `codex` CLI, for the runner conformance suite (runner/tests/test_conformance.py):
`--version`, `login status`, and `app-server` speaking the part of the JSON-RPC protocol runner/hosts/codex.py
uses (scripts/journey-fake-codex.py, plus token usage). Every thread and turn request is appended to $FAKE_LOG. A
prompt containing HANG streams one delta and then waits, once per $FAKE_LOG, until its parent goes away."""
import json
import os
import sys
import time

GRANTED = ("ACME_API_KEY", "HUB_TOKEN", "HUB_API_URL", "HUB_BOT", "TICO_CRED_SOCKET")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def record(entry):
    with open(os.environ["FAKE_LOG"], "a") as log:
        log.write(json.dumps(entry) + "\n")


def main():
    if "--version" in sys.argv:
        print("codex-cli 99.0.0")
        return
    if sys.argv[1:3] == ["login", "status"]:
        print("Logged in using ChatGPT")
        return
    if sys.argv[1:2] != ["app-server"]:
        sys.exit(2)
    threads, turns, parent, cwd = 0, 0, os.getppid(), {}
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, params, rid = msg.get("method"), msg.get("params") or {}, msg.get("id")
        if rid is None:
            continue
        if method in ("thread/start", "thread/resume"):
            threads += 1
            thread = params.get("threadId") or "acme-thread-%d-%d" % (os.getpid(), threads)
            cwd[thread] = params.get("cwd") or os.getcwd()
            record({"harness": "codex", "method": method, "thread": thread})
            send({"id": rid, "result": {"thread": {"id": thread}}})
        elif method == "turn/start":
            turns += 1
            thread, turn = params["threadId"], "acme-turn-%d" % turns
            text = " ".join(part.get("text", "") for part in params.get("input", []))
            record({"harness": "codex", "method": method, "thread": thread, "prompt": text,
                    "env": {k: os.environ.get(k) for k in GRANTED}})
            send({"id": rid, "result": {"turn": {"id": turn}}})
            send({"method": "turn/started", "params": {"threadId": thread, "turn": {"id": turn}}})
            marker = os.environ["FAKE_LOG"] + ".hung"
            if "HANG" in text and not os.path.exists(marker):
                open(marker, "w").close()
                send({"method": "item/agentMessage/delta", "params": {"threadId": thread, "turnId": turn, "delta": "Working on it"}})
                while os.getppid() == parent:
                    time.sleep(0.1)
                return
            if "PUBLISH" in text:                # a deliverable the runner publishes as a Tico file
                os.makedirs(os.path.join(cwd.get(thread, os.getcwd()), "reports"), exist_ok=True)
                with open(os.path.join(cwd.get(thread, os.getcwd()), "reports", "acme.md"), "w") as report:
                    report.write("# Acme report\n")
            reply = "Acme reply."
            if os.environ.get("ACME_API_KEY"):
                reply += " The key is " + os.environ["ACME_API_KEY"]
            for chunk in (reply[:5], reply[5:]):
                send({"method": "item/agentMessage/delta", "params": {"threadId": thread, "turnId": turn, "delta": chunk}})
            send({"method": "item/completed", "params": {"threadId": thread, "turnId": turn,
                  "item": {"type": "agentMessage", "id": "m%d" % turns, "text": reply, "phase": "final_answer"}}})
            send({"method": "thread/tokenUsage/updated", "params": {"threadId": thread, "turnId": turn, "tokenUsage": {
                "total": {"inputTokens": 7 * turns, "cachedInputTokens": 3 * turns, "outputTokens": 2 * turns, "totalTokens": 9 * turns},
                "last": {"inputTokens": 7, "cachedInputTokens": 3, "outputTokens": 2, "totalTokens": 9}}}})
            send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": turn, "status": "completed"}}})
        else:
            send({"id": rid, "result": {}})


if __name__ == "__main__":
    main()
