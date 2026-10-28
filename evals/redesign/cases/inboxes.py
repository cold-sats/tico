"""Inboxes (PLAN §7, scenarios 16-21): a message trigger on an inbox with its Filter, Decide, Paths and LLM steps, the send
switch and batch timing. CONTRACT §2 names the saved shape of each, so a saved-shape check reads the flow back (a real GET)
and checks the named fields. A received mail reaching the inbox is CONTRACT gap (a): no route delivers one to a message
trigger, so every check that needs a mail to arrive is an untestable CONTRACT gap with its reason on the check."""
from ..harness import CHRIS_REF, W3, Check, Scenario, auto_id, automation, body, setup, untestable

INBOX = "chris@tico.team"
TIMES = ["08:00", "13:00", "17:00"]
BUCKET = {"bucket": {"type": "choice", "instructions": "Reply, or archive as noise?",
                     "criteria": {"reply": "needs an answer", "archive": "noise"}}}
NO_MAIL = "CONTRACT names no route that delivers a received mail to a message trigger (gap a)"


# ---------------------------------------------------------------------------------------------- helpers
def cond(field, op, value, **extra):
    return {"field": field, "op": op, "value": value, **extra}


def node(sid, kind, **fields):
    return {"id": sid, "type": kind, "enabled": True, **fields}


def inbox_trigger(**extra):
    return {"type": "message", "inbox": INBOX, **extra}


def flow_of(data):
    return data.get("automation", data) if isinstance(data, dict) else {}


def read_auto(org, facts, key="auto"):
    return org.api("get", f"/api/v2/automations/{auto_id(facts, key)}", wave=W3)


def read_flow(f):
    """The saved flow, read back from the server; raises unless the create and the read were both 2xx."""
    setup(f, "auto", "read")
    return flow_of(body(f, "read"))


def steps_of(flow, kind):
    return [s for s in flow.get("steps") or [] if s.get("type") == kind]


# ---------------------------------------------------------------------------------------------- 16 filter archive
def s16_steps(org, f):
    org.step(f, "auto", automation, org, "Inbox · chris", CHRIS_REF,
             trigger=inbox_trigger(filters=[cond("message.from", "contains", "promo")]),
             steps=[node("sort", "filter", rules=[{"when": [cond("message.from", "contains", "promo")],
                                                   "match": "all", "then": [{"do": "archive", "args": {}}],
                                                   "stop": True}])])
    org.step(f, "read", read_auto, org, f)


def filtered_saved(f):
    trigger = read_flow(f).get("trigger") or {}
    filters = trigger.get("filters") or []
    ok = trigger.get("type") == "message" and trigger.get("inbox") == INBOX and bool(filters) \
        and filters[0].get("field") == "message.from"
    return ok, f"trigger {trigger}"


# ---------------------------------------------------------------------------------------------- 17 decide questions
def s17_steps(org, f):
    org.step(f, "auto", automation, org, "Triage · chris", CHRIS_REF, trigger=inbox_trigger(), steps=[
        node("rank", "decide", questions=BUCKET, level="medium", out="d1"),
        node("reply", "filter", rules=[{"when": [cond("d1.bucket", "is", "reply", min=0.7)], "match": "all",
                                         "then": [{"do": "draft_reply", "args": {}}], "stop": True}])])
    org.step(f, "read", read_auto, org, f)


def decide_saved(f):
    decide = next(iter(steps_of(read_flow(f), "decide")), {})
    ok = "bucket" in (decide.get("questions") or {}) and decide.get("level") == "medium" and decide.get("out") == "d1"
    return ok, f"decide {decide}"


# ---------------------------------------------------------------------------------------------- 18 paths on outputs
def s18_steps(org, f):
    org.step(f, "auto", automation, org, "Route mail · chris", CHRIS_REF, trigger=inbox_trigger(), steps=[
        node("rank", "decide", questions=BUCKET, level="medium", out="d1"),
        node("fork", "paths", paths=[
            {"name": "reply", "when": [cond("d1.bucket", "is", "reply", min=0.7)],
             "steps": [node("r", "action", do="draft_reply", args={})]},
            {"name": "archive", "when": [cond("d1.bucket", "is", "archive", min=0.7)],
             "steps": [node("a", "action", do="archive", args={})]}],
         otherwise={"steps": [node("o", "action", do="note", args={"text": "unsure"})]})])
    org.step(f, "read", read_auto, org, f)


def paths_saved(f):
    fork = next(iter(steps_of(read_flow(f), "paths")), {})
    ok = len(fork.get("paths") or []) == 2 and fork.get("otherwise") is not None
    return ok, f"paths step {fork}"


# ---------------------------------------------------------------------------------------------- 19 assistant turn
def s19_steps(org, f):
    org.step(f, "auto", automation, org, "Assistant · chris", CHRIS_REF, trigger=inbox_trigger(), steps=[
        {"id": "ask", "type": "llm", "enabled": True, "as": "assistant:chris", "prompt": "Draft a reply",
         "out": "txt"}])
    org.step(f, "read", read_auto, org, f)


def assistant_saved(f):
    llm = next(iter(steps_of(read_flow(f), "llm")), {})
    return llm.get("as") == "assistant:chris", f"llm step {llm}"


# ---------------------------------------------------------------------------------------------- 20 send switch
def s20_steps(org, f):
    org.step(f, "auto", automation, org, "Replies · chris", CHRIS_REF, trigger=inbox_trigger(),
             steps=[node("send", "action", do="send_reply", args={})])
    org.step(f, "read", read_auto, org, f)


def send_saved(f):
    sends = [s for s in read_flow(f).get("steps") or [] if s.get("do") == "send_reply"]
    return len(sends) == 1, f"{len(sends)} send_reply step(s), want 1"


# ---------------------------------------------------------------------------------------------- 21 batched
def s21_steps(org, f):
    org.step(f, "auto", org.api, "post", "/api/v2/automations", {
        "name": "Batch · chris", "owner": CHRIS_REF, "enabled": True, "builtin": False,
        "batch": {"times": TIMES}, "trigger": inbox_trigger(), "steps": [node("gate", "filter", rules=[])]}, wave=W3)
    org.step(f, "read", read_auto, org, f)


def batch_saved(f):
    batch = read_flow(f).get("batch")
    return batch == {"times": TIMES}, f"batch {batch}, want {{'times': {TIMES}}}"


SCENARIOS = [
    Scenario(16, "inbox-filter-archive", "Inbox filter: matching mail is archived, the rest left; dropped mail only counted",
             s16_steps, [
                 Check("an inbox automation with a filtered message trigger is saved", W3, filtered_saved),
                 Check("mail matching the filter is archived", W3, untestable(NO_MAIL)),
                 Check("mail the filter does not match stays in the inbox", W3, untestable(NO_MAIL)),
                 Check("a trigger its filters drop writes a daily count, no run row", W3,
                       untestable(NO_MAIL + "; the daily count has no read route either (gap e)")),
             ]),
    Scenario(17, "inbox-decide-questions", "Inbox Decide: a question set answered, the reply rule gated on min confidence",
             s17_steps, [
                 Check("a Decide step on a question set is saved with level and out", W3, decide_saved),
                 Check("the judge is asked with the mail's state and the decide level", W3,
                       untestable("the judge engine takes no level, though decide carries one (gap c); " + NO_MAIL)),
                 Check("a reply at confidence 0.8 passes min 0.7 and drafts", W3, untestable(NO_MAIL)),
                 Check("a reply at confidence 0.6 fails min 0.7 and does not draft", W3, untestable(NO_MAIL)),
             ]),
    Scenario(18, "inbox-paths-on-outputs", "Inbox paths on a Decide output: first match runs, no rejoin", s18_steps, [
        Check("a paths step on a Decide output is saved with two paths and otherwise", W3, paths_saved),
        Check("the first matching path runs for one mail", W3, untestable(NO_MAIL)),
        Check("a path does not rejoin the steps after the fork", W3, untestable(NO_MAIL)),
    ]),
    Scenario(19, "inbox-assistant-turn", "Inbox LLM as Chris's Assistant: created on first use, never in the sender's session",
             s19_steps, [
                 Check("an LLM step as assistant:chris is saved", W3, assistant_saved),
                 Check("the first mail creates Chris's Assistant", W3,
                       untestable("CONTRACT names no Assistant read or create route (gap d); " + NO_MAIL)),
                 Check("the Assistant's turn never starts in the sender's session", W3,
                       untestable("CONTRACT names no read of which session ran a turn (gap e)")),
             ]),
    Scenario(20, "inbox-send-switch", "Inbox send switch: reply sent when on; draft and send_off logged when off", s20_steps, [
        Check("a send_reply step is saved", W3, send_saved),
        Check("with the send switch on, a reply is sent", W3, untestable(NO_MAIL)),
        Check("with the switch off, a draft is saved and send_off is logged", W3,
              untestable("CONTRACT names no route for the inbox send switch (gap d)")),
    ]),
    Scenario(21, "inbox-batched", "Inbox batch: Filter on receipt, the rest at the batch times", s21_steps, [
        Check("batch times are saved and read back", W3, batch_saved),
        Check("the Filter runs on receipt; the other steps wait for the batch times", W3, untestable(NO_MAIL)),
        Check("mail that arrives between batch times waits for the next one", W3, untestable(NO_MAIL)),
    ]),
]
