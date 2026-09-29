"""`hub docs ask "question"`: ask the Librarian and wait for its answer (docs/librarian.md).

A bot sends the Librarian an `ask` message, the ordinary ask and answer path, and waits for the answer
the way `hub ask` does. A person's script (or the Assistant, acting as that person) uses the route the
Docs page uses, `POST /api/v2/docs/ask`, which puts the question in their own private docs conversation,
then waits for the reply there. Either way the result is the same:

    {"answer": "...", "citations": [{"type": "internal", "title": "...", "url_or_id": "<doc id>"},
                                    {"type": "linked", "title": "...", "url_or_id": "https://..."}],
     "covered": true}

`covered` is false when the Librarian said the docs do not cover the question (its answer then starts
"Not in the docs"). A wait that runs out is `{"timeout": true}`.
"""

import re
import time

LIBRARIAN = "librarian"
WAIT_MAX = 300
# The Librarian's citations: [Internal doc · Title](doc:<id>) and [Linked · host or title](https://...).
CITATION = re.compile(r"\[(Internal doc|Linked) · ([^\]]+)\]\((doc:[^)\s]+|https?://[^)\s]+)\)")


def parse_citations(text):
    found, seen = [], set()
    for kind, title, target in CITATION.findall(str(text or "")):
        internal = kind == "Internal doc"
        if internal != target.startswith("doc:"):
            continue                    # an internal citation is a doc id, a linked one is a web address
        ref = target[len("doc:"):] if target.startswith("doc:") else target
        if (internal, ref) not in seen:
            seen.add((internal, ref))
            found.append({"type": "internal" if internal else "linked", "title": title.strip(), "url_or_id": ref})
    return found


def covered(text):
    return not str(text or "").lstrip().lower().startswith("not in the docs")


def result(text):
    return {"answer": text, "citations": parse_citations(text), "covered": covered(text)}


def ask(api, question, wait_s=120, key=None, sleep=time.sleep, clock=time.monotonic):
    wait = max(0, min(int(wait_s or 0), WAIT_MAX))
    deadline = clock() + wait
    suffix = (lambda s: key + s) if key else (lambda s: None)
    if api.get("me").get("role") == "bot":
        msg = api.post("messages", {"to": LIBRARIAN, "text": question, "kind": "ask", "wait_s": wait},
                       key=suffix(":ask"))
        while True:
            answers = api.get("answers", ids=msg["id"])
            if msg["id"] in answers:
                answer = answers[msg["id"]]
                api.post(f"messages/{answer['id']}/ack", {}, key=suffix(":ack"))
                return result(answer["body"])
            if clock() >= deadline:
                return {"timeout": True}
            sleep(1)
    sent = api.post("docs/ask", {"question": question}, key=suffix(":ask"))
    while True:
        snapshot = api.get(f"conversations/{sent['conversation_id']}/snapshot")
        for message in snapshot.get("messages") or []:
            if message.get("in_reply_to") == sent["message_id"] and message.get("from_actor") == "bot:" + LIBRARIAN:
                return result(message["body"])
        if clock() >= deadline:
            return {"timeout": True}
        sleep(2)
