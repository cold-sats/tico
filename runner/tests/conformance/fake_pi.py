"""A stand-in for the Pi coding agent (`pi`), for the runner conformance suite (runner/tests/test_conformance.py).

`--version` answers as pi 0.70.0. `--mode json -p` reads the prompt from stdin and writes the JSON lines
runner-rs/src/hosts/pi.rs reads (runner/tests/fixtures/pi/turn.jsonl): `session`, two text deltas, the assistant
message's end with its usage, `turn_end` and `agent_end`. Every call is appended to $FAKE_LOG as one JSON line
(argv, the prompt, the granted variables). A prompt containing HANG streams one delta and then waits, once per
$FAKE_LOG, until its parent goes away."""
import json
import os
import sys
import time

GRANTED = ("ACME_API_KEY", "HUB_TOKEN", "HUB_API_URL", "HUB_BOT", "TICO_CRED_SOCKET", "OPENROUTER_API_KEY")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def flag(args, name):
    return args[args.index(name) + 1] if name in args else None


def delta(text):
    send({"type": "message_update", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
          "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": text}})


def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        print("0.70.0")
        return
    parent = os.getppid()
    text = sys.stdin.read()
    with open(os.environ["FAKE_LOG"], "a") as log:
        log.write(json.dumps({"harness": "pi", "argv": args, "prompt": text, "cwd": os.getcwd(),
                              "env": {k: os.environ.get(k) for k in GRANTED}}) + "\n")
    send({"type": "session", "version": 3, "id": flag(args, "--session-id"), "cwd": os.getcwd()})
    send({"type": "agent_start"})
    marker = os.environ["FAKE_LOG"] + ".hung"
    if "HANG" in text and not os.path.exists(marker):
        open(marker, "w").close()
        delta("Working on it")
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
        delta(chunk)
    message = {"role": "assistant", "content": [{"type": "text", "text": reply}],
               "usage": {"input": 7, "output": 2, "cacheRead": 3, "cacheWrite": 0, "totalTokens": 12}}
    send({"type": "message_end", "message": message})
    send({"type": "turn_end", "message": message, "toolResults": []})
    send({"type": "agent_end", "messages": []})


if __name__ == "__main__":
    main()
