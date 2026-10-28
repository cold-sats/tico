"""The automation executor: a flow, the trigger's payload and injected services in; a run record out.

Pure. Everything with an effect (the judge, actions, turns, finding items, the clock and the spend so far) is a
method of `services`, so a test hands in fakes and the hub hands in the real thing (backend/automations.py).

A run is a list of threads. A thread is where one item is in the flow: the outputs it has gathered and a cursor,
the forks it took (`trail`) and the next step in that list. Paths never rejoin and a `paths` step ends its list, so
that cursor is the whole position. A run starts with one thread; a `find` replaces it with one per item.

A thread stops when its list ends, a filter rule says stop, a fork has no path or a step fails. A turn over the spend
cap is recorded as `spend_cap` and the thread goes on without it; a decision with Decide off is `skipped` likewise. It waits for two things: the answer of an `llm` turn that has steps after it (`answer` fills it) and,
with `batch` times, the next batch time once the leading filters ran (`advance` picks it up when the time comes).

services:
  judge(values, questions, label, level) -> {"answers": {...}, "cost_usd": n}, or None while Decide is off
  question_set(ref) -> questions
  act(do, args, ctx) -> {"ok": bool, "detail": str, ...}
  start_turn(who, prompt, ctx, wait) -> {"ref": str, "turn": {bot, task, session}}
  find(source, query, limit) -> [item, ...]
  spent_30m() -> dollars this automation's other runs spent in the last 30 minutes
  next_batch() -> the next batch time (ISO), and now() -> now (ISO)
"""
from backend import automation_flow as F

READY, WAITING, DONE, FAILED = "ready", "waiting", "done", "failed"


def start(payload, *, manual=False):
    """A new run's state: one thread at the first step."""
    return {"status": "running", "cost": 0.0, "steps": [], "payload": payload or {}, "manual": bool(manual),
            "empty": False, "threads": [_thread(None, None, {}, [], 0)]}


def _thread(item, value, outputs, trail, at, batched=False):
    return {"item": item, "value": value, "outputs": dict(outputs), "trail": list(trail), "next": at,
            "state": READY, "wait": None, "batched": batched}


def execute(flow, payload, services, *, manual=False):
    return advance(flow, start(payload, manual=manual), services)


def steps_at(flow, trail):
    """The step list a cursor's trail leads to."""
    steps = flow.get("steps") or []
    for index, branch in trail:
        fork = steps[index]
        steps = ((fork.get("otherwise") or {}).get("steps") if branch == "otherwise"
                 else fork["paths"][branch].get("steps")) or []
    return steps


def values_of(state, thread):
    """What a condition, a prompt and an action's args read: the payload (also as `trigger`), the thread's outputs,
    and the item a `find` gave it."""
    payload = state["payload"]
    out = {**payload, "trigger": payload, **thread["outputs"]}
    if thread["item"] is not None:
        out["item"] = thread["value"]
    return out


def answer(state, ref, text, cost=0.0, ok=True):
    """An `llm` turn finished: its thread gets the text as the step's output and is ready again; a turn that did not
    finish (`ok` false) fails the thread. Returns whether a waiting thread had that ref."""
    for thread in state["threads"]:
        wait = thread.get("wait") or {}
        if thread["state"] == WAITING and wait.get("kind") == "turn" and wait.get("ref") == ref:
            record = state["steps"][wait["record"]]
            outputs = ({**record["outputs"], "text": text} if ok
                       else {**record["outputs"], "error": str(text or "the turn did not finish")[:300]})
            record.update(status="ok" if ok else "failed", outputs=outputs, cost=round(record["cost"] + cost, 6))
            state["cost"] = round(state["cost"] + cost, 6)
            if ok:
                thread["outputs"][wait["out"]] = outputs
            thread.update(state=READY if ok else FAILED, wait=None)
            if not ok:
                state["status"] = _status(state)
            return True
    return False


def charge(state, ref, cost):
    """What a turn the run started (`ref`) cost, once it ends, on its step and the run. Returns whether `ref` is one."""
    for record in state["steps"]:
        if (record.get("outputs") or {}).get("ref") == ref and record["type"] in ("llm", "bot_turn"):
            record["cost"] = round(record["cost"] + cost, 6)
            state["cost"] = round(state["cost"] + cost, 6)
            return True
    return False


def advance(flow, state, services):
    """Run every ready thread (and every batch wait whose time has come) until it ends or waits."""
    now = services.now()
    for thread in state["threads"]:
        wait = thread.get("wait") or {}
        if thread["state"] == WAITING and wait.get("kind") == "batch" and wait["until"] <= now:
            thread.update(state=READY, wait=None)
    threads, n = state["threads"], 0
    while n < len(threads):   # a find puts its items' threads in the place of its own
        if threads[n]["state"] == READY:
            _step(flow, state, threads[n], services)
        else:
            n += 1
    state["status"] = _status(state)
    return state


def _status(state):
    states = {t["state"] for t in state["threads"]}
    if WAITING in states:
        return "waiting"
    if FAILED in states:
        return "failed"
    if state["empty"] and not state["threads"]:
        return "empty"
    if state["steps"] and all(r["status"] == "skipped" for r in state["steps"]):
        return "skipped"
    return "ok"


def _record(state, thread, step, status, outputs=None, cost=0.0):
    record = {"id": step["id"], "type": step["type"], "status": status, "outputs": outputs or {},
              "cost": round(cost, 6)}
    if thread["item"] is not None:
        record["item"] = thread["item"]
    state["steps"].append(record)
    state["cost"] = round(state["cost"] + cost, 6)
    return len(state["steps"]) - 1


def _capped(flow, state, services):
    cap = (flow.get("spend_cap") or {}).get("per_30m")
    return cap is not None and services.spent_30m() + state["cost"] >= float(cap)


def _step(flow, state, thread, services):
    """Run the thread's next step, or end it at the end of its list."""
    steps = steps_at(flow, thread["trail"])
    if thread["next"] >= len(steps):
        thread["state"] = DONE
        return
    step = steps[thread["next"]]
    if (flow.get("batch") and not state["manual"] and not thread["batched"] and not thread["trail"]
            and step["type"] != "filter"):
        # Filter on receipt, the rest at the next batch time.
        thread.update(state=WAITING, wait={"kind": "batch", "until": services.next_batch()}, batched=True)
        return
    thread["next"] += 1
    if step.get("enabled", True) is False:
        _record(state, thread, step, "skipped")
        return
    try:
        RUN[step["type"]](flow, state, thread, step, services)
    except Exception as exc:  # noqa: BLE001 - a service's failure is the step's, recorded on the run
        _record(state, thread, step, "failed", {"error": (str(exc) or type(exc).__name__)[:300]})
        thread["state"] = FAILED


def _filter(flow, state, thread, step, services):
    values = values_of(state, thread)
    for n, rule in enumerate(step.get("rules") or []):
        if not F.all_hold(rule.get("when") or [], values, rule.get("match", "all")):
            continue
        done = [_act(services, action["do"], action.get("args") or {}, values, step) for action in rule.get("then") or []]
        failed = [d for d in done if not d.get("ok")]
        _record(state, thread, step, "failed" if failed else "ok", {"rule": n, "actions": done})
        if failed:
            thread["state"] = FAILED
        elif rule.get("stop"):
            thread["state"] = DONE
        return
    _record(state, thread, step, "ok", {"rule": None, "actions": []})


def _act(services, do, args, values, step):
    result = services.act(do, F.render_args(args, values), {"values": values, "step": step["id"]})
    return {"do": do, **result}


def _decide(flow, state, thread, step, services):
    questions = step.get("questions") or services.question_set(step["set"])
    values = values_of(state, thread)
    level = step.get("level", "low")
    result = services.judge(values, questions, f"automation.{step['id']}", level)
    if result is None:
        # Decide is off (no decision model, or the month's cap): carry on as callers elsewhere do, with no answers,
        # so a path on them falls to Otherwise.
        thread["outputs"][step["out"]] = {}
        _record(state, thread, step, "skipped", {"off": True, "level": level})
        return
    answers = result.get("answers") or {}
    thread["outputs"][step["out"]] = answers
    _record(state, thread, step, "ok", {**answers, "level": level}, float(result.get("cost_usd") or 0))


def _turn(flow, state, thread, step, services, who, prompt, wait):
    if _capped(flow, state, services):
        # The cap stops spending, not the run: later filters, decisions and actions still go.
        _record(state, thread, step, "spend_cap")
        return
    values = values_of(state, thread)
    started = services.start_turn(who, F.render(prompt, values), {"values": values, "step": step["id"]}, wait)
    ref = started["ref"]
    outputs = {"ref": ref, **({"turn": started["turn"]} if started.get("turn") else {})}
    if not wait:
        _record(state, thread, step, "ok", outputs)
        return
    record = _record(state, thread, step, "waiting", outputs)
    thread.update(state=WAITING, wait={"kind": "turn", "ref": ref, "out": step["out"], "record": record})


def _llm(flow, state, thread, step, services):
    # Nothing after it reads the answer: the turn runs on its own and the run does not wait.
    rest = thread["next"] < len(steps_at(flow, thread["trail"]))
    _turn(flow, state, thread, step, services, step["as"], step["prompt"], rest)


def _bot_turn(flow, state, thread, step, services):
    bot = step["bot"]
    _turn(flow, state, thread, step, services, bot if bot.startswith("bot:") else "bot:" + bot, step["prompt"], False)


def _find(flow, state, thread, step, services):
    values = values_of(state, thread)
    items = list(services.find(step["source"], F.render(step.get("query") or "", values), step.get("limit", 20)))
    _record(state, thread, step, "ok", {"count": len(items)})
    state["empty"] = not items
    place = next(n for n, t in enumerate(state["threads"]) if t is thread)
    state["threads"][place:place + 1] = [
        _thread(n, item, thread["outputs"], thread["trail"], thread["next"], thread["batched"])
        for n, item in enumerate(items)]


def _paths(flow, state, thread, step, services):
    values = values_of(state, thread)
    index = thread["next"] - 1
    for n, path in enumerate(step.get("paths") or []):
        if F.all_hold(path.get("when") or [], values, path.get("match", "all")):
            _record(state, thread, step, "ok", {"path": path["name"]})
            thread["trail"].append([index, n])
            thread["next"] = 0
            return
    if step.get("otherwise") is not None:
        _record(state, thread, step, "ok", {"path": "otherwise"})
        thread["trail"].append([index, "otherwise"])
        thread["next"] = 0
        return
    _record(state, thread, step, "ok", {"path": None})
    thread["state"] = DONE


def _action(flow, state, thread, step, services):
    values = values_of(state, thread)
    result = _act(services, step["do"], step.get("args") or {}, values, step)
    thread["outputs"][step["id"]] = result
    _record(state, thread, step, "ok" if result.get("ok") else "failed", result)
    if not result.get("ok"):
        thread["state"] = FAILED


RUN = {"filter": _filter, "decide": _decide, "llm": _llm, "bot_turn": _bot_turn, "find": _find, "paths": _paths,
       "action": _action}


def view(state):
    """The run record's public part (CONTRACT §2): status, cost and the step records."""
    return {"status": state["status"], "cost": state["cost"], "steps": state["steps"]}
