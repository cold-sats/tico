"""Fakes for the redesign scenarios. Each one is a copy, cut down to what the scenarios call, of a fake the backend
suite already uses (the source line is in its docstring), except the Gmail fake, which is imported unchanged. Nothing
here reaches a network or a real service.

The judge is a replay. A call is answered from the next scripted answer when the caller passed one, else from
recordings/<key>.json (real model output, saved once by `python -m evals.redesign.record`), else MissingRecording.
REDESIGN_LIVE=1 turns on the live sample (5% of recorded calls, at most 10 a run). The live call is not built: only the
decision is, and go_live says so."""
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import httpx

from connectors.mail.tests.fake import FakeGmailService  # noqa: F401 (the mail tests' own fake, unchanged)
from .harness import GAP, Unmet

RECORDINGS = Path(__file__).parent / "recordings"
LIVE_RATE, LIVE_MAX = 0.05, 10
PUBLIC = [ipaddress.ip_address("93.184.216.34")]   # backend/tests/test_webhooks.py:20


class MissingRecording(LookupError):
    """No recording and no scripted answer for this judge call."""


def recording_key(state, questions, level):
    """A recording's name: a hash of what the judge was asked (state, questions and the decide level)."""
    blob = json.dumps({"state": state, "questions": questions, "level": level}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class ReplayJudge:
    """app.state.judge for the scenarios. Same call shape as backend/tests/test_judge.py:16 FakeJudge, which keeps
    every call. `script` is a list of answer dicts, used first and in order, so a routing check gets the exact
    confidence it scripted; once it is spent, a recording answers. A scripted answer stands in for a model answer, so
    checks read routing and storage, never the model."""

    def __init__(self, script=(), fail=None):
        self.script, self.fail, self.calls = list(script), fail, []

    def __call__(self, state, questions, label=None, level=None):
        self.calls.append({"state": state, "questions": questions, "label": label, "level": level})
        if self.fail:
            raise self.fail
        if level is None:
            # The engine callable takes no level, but CONTRACT §2 puts decide.level on the step: the replay key needs it.
            raise Unmet(GAP, "the judge engine is called without a level, and CONTRACT §2 names decide.level")
        if self.script:
            # A passed script wins over a recording: a named scenario needs the exact confidence it scripted.
            return {"model": "scripted", "usage": {"input_tokens": 0, "output_tokens": 0}, "ms": 0,
                    "answers": self.script.pop(0)}
        path = RECORDINGS / f"{recording_key(state, questions, level)}.json"
        if path.exists():
            saved = json.loads(path.read_text())
            return {name: saved[name] for name in ("model", "usage", "ms", "answers")}
        raise MissingRecording(
            f"no recording recordings/{path.name} and no scripted answer for this call; re-record with "
            "`python -m evals.redesign.record` (the recorder needs live credentials: HUB_API_URL and HUB_TOKEN, "
            "or TYPESAFE_API_KEY)")


def live_sample(rng, sent_so_far):
    """Whether one recorded call also goes live this run: off unless REDESIGN_LIVE=1, 5% a call, 10 a run at most."""
    if os.environ.get("REDESIGN_LIVE") != "1" or sent_so_far >= LIVE_MAX:
        return False
    return rng.random() < LIVE_RATE


def go_live(*_args, **_kwargs):
    raise NotImplementedError("live: not built")


def attach_judge(org, engine):
    """Puts the engine where the hub reads its judge: app.state.judge, as backend/tests/test_judge.py sets it."""
    org.app.state.judge = engine
    return engine


class FakeSlack:
    """backend/tests/test_slack_gateway.py:55 FakeSlack, cut to what a reply records: every post_message it made.
    Waits for the Slack ingest route; no scenario calls it yet."""

    def __init__(self):
        self.posts = []

    def post_message(self, channel, thread_ts, text, username=None, icon_emoji=None, icon_url=None):
        self.posts.append({"channel": channel, "thread_ts": thread_ts, "text": text, "username": username,
                           "icon_emoji": icon_emoji, "icon_url": icon_url})
        return {"ok": True, "ts": str(len(self.posts))}


def hook(client, url, body=b'{"order": 42}', headers=None):
    """backend/tests/test_triggers.py:8 hook: one delivery to an incoming address, as the outside world sends it."""
    return client.post(urlsplit(url).path, content=body,
                       headers={"content-type": "application/json", **(headers or {})})


def stripe_sig(secret, body, t):
    """backend/tests/test_triggers_incoming.py:16 stripe_sig: Stripe's scheme, t=<unix>,v1=<HMAC-SHA256 of "<t>.<body>">."""
    return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()


class Receiver:
    """The far end of an outgoing webhook: backend/tests/test_webhooks.py:37 `net` fixture. Every request is kept and
    `reply` decides the answer. Pair with deliver(), which resolves every name to PUBLIC as the fixture does."""

    def __init__(self, reply=None):
        self.seen = []
        self.reply = reply or (lambda request: httpx.Response(200))
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request):
        self.seen.append(request)
        return self.reply(request)


def deliver(app, receiver, rehearsal=False):
    """Runs the outgoing webhook queue until it is empty, through the receiver (test_webhooks.py:72). Returns the count."""
    from backend import egress, webhook_delivery as D
    sent = 0
    with mock.patch.object(egress, "resolve", lambda host: PUBLIC):
        while D.step(app.state.store, app.state.vault, rehearsal=rehearsal, transport=receiver.transport):
            sent += 1
    return sent
