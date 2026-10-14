"""A stand-in for the `claude` CLI, for the runner conformance suite (runner/tests/test_conformance.py).

`--version`, `--help` and `auth status --json` answer as Claude Code 2.1.296 does; `-p` speaks stream-json the way
runner/hosts/claude.py reads it: each user message is replayed, then a text delta, the assistant message and a
`result`. Every call is appended to $FAKE_LOG as one JSON line (argv, the prompt, the granted variables). A prompt
containing HANG streams one delta and then waits, once per $FAKE_LOG, until its parent goes away."""
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


def flag(name):
    args = sys.argv[1:]
    return args[args.index(name) + 1] if name in args else None


def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        print("2.1.296 (Claude Code)")
        return
    if args == ["--help"]:
        print("Usage: claude [options]\n  --autocompact <tokens>  compact the conversation at this many tokens")
        return
    if args[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
        return
    session = flag("--session-id") or flag("--resume")
    parent = os.getppid()
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        text = " ".join(part.get("text", "") for part in message["message"]["content"])
        record({"harness": "claude", "argv": args, "prompt": text, "env": {k: os.environ.get(k) for k in GRANTED}})
        send({**message, "isReplay": True})
        send({"type": "system", "subtype": "init", "session_id": session, "model": "claude-sonnet-5", "tools": []})
        send({"type": "stream_event", "event": {"type": "message_start", "message": {"id": "msg_1"}}, "parent_tool_use_id": None})
        marker = os.environ["FAKE_LOG"] + ".hung"
        if "HANG" in text and not os.path.exists(marker):
            open(marker, "w").close()
            send({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                  "delta": {"type": "text_delta", "text": "Working on it"}}, "parent_tool_use_id": None})
            while os.getppid() == parent:
                time.sleep(0.1)
            return
        if "PUBLISH" in text:                    # a deliverable the runner publishes as a Tico file
            os.makedirs("reports", exist_ok=True)
            with open(os.path.join("reports", "acme.md"), "w") as report:
                report.write("# Acme report\n")
        reply = "Acme reply."
        if os.environ.get("ACME_API_KEY"):
            reply += " The key is " + os.environ["ACME_API_KEY"]
        for chunk in (reply[:5], reply[5:]):
            send({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                  "delta": {"type": "text_delta", "text": chunk}}, "parent_tool_use_id": None})
        send({"type": "assistant", "message": {"id": "msg_1", "role": "assistant", "content": [{"type": "text", "text": reply}]},
              "parent_tool_use_id": None})
        send({"type": "result", "subtype": "success", "is_error": False, "result": reply, "stop_reason": "end_turn",
              "session_id": session, "total_cost_usd": 0.01,
              "usage": {"input_tokens": 7, "cache_read_input_tokens": 3, "output_tokens": 2}})


if __name__ == "__main__":
    main()
