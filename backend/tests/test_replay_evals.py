"""Behaviour replay (evals/replay/) without a model: a finished task splits into its opening state and its outcome,
a case nobody signed or that still holds a secret is refused, and a replay on a fake server is scored against the
original with the same scorers and reported as a win or a regression.

The live runner needs a scratch team with a real model and runs only at release preparation (docs/releasing.md).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPLAY = Path(__file__).resolve().parents[2] / "evals" / "replay"
sys.path.insert(0, str(REPLAY))
import replay  # noqa: E402

_spec = importlib.util.spec_from_file_location("replay_run", REPLAY / "run.py")
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)


def message(mid, actor, body, created, kind="say"):
    return {"id": mid, "from_actor": actor, "body": body, "created": created, "kind": kind}


def test_capture_splits_opening_state_from_outcome_and_needs_a_signature():
    detail = {"task": {"id": "t1", "title": "Fix the login page", "body": "It 500s.", "owner": "bot:dev",
                       "status": "done", "acceptance_criteria": []},
              "runs": [{"started": "2026-10-16T10:00:00Z", "finished": "2026-10-16T10:06:00Z"},
                       {"started": "2026-10-16T11:00:00Z", "finished": "2026-10-16T11:03:00Z"}],
              "messages": [message("n", "keeper", "New task from human:ana", "2026-10-16T09:59:00Z", "notice"),
                           message("a", "human:ana", "Only the login page.", "2026-10-16T09:58:00Z"),
                           message("b", "bot:dev", "Which browser?", "2026-10-16T10:05:00Z"),
                           message("c", "human:ana", "Safari.", "2026-10-16T10:30:00Z"),
                           message("d", "bot:dev", "Fixed in PR 12.", "2026-10-16T11:02:00Z")],
              "comments": [message("a", "human:ana", "Only the login page.", "2026-10-16T09:58:00Z")]}
    files = {"files": [{"name": "trace.txt", "versions": [{"n": 1, "by": "human:ana", "created": "2026-10-16T09:57:00Z",
                                                           "text": "Traceback"}]},
                       {"name": "fix.diff", "versions": [{"n": 1, "by": "bot:dev", "created": "2026-10-16T11:01:00Z"}]}]}
    case = replay.split(detail, files, {"content": "# Dev", "updated": "2026-10-15T00:00:00Z"})

    assert case["conversation"] == [{"from": "person", "text": "Only the login page."}]
    assert case["files"] == [{"name": "trace.txt", "text": "Traceback"}]
    assert case["original"] | {"transcript": None} == {
        "status": "done", "transcript": None, "files": ["fix.diff"], "runs": 2, "minutes": 9.0, "person_steps": 1}
    assert case["original"]["transcript"] == [["bot", "Which browser?"], ["person", "Safari."], ["bot", "Fixed in PR 12."]]
    assert case["prompt"] == {"sha256": replay.sha("# Dev"), "updated": "2026-10-15T00:00:00Z", "exact": True}
    # A draft is never runnable: a person signs it, and a secret left in it refuses it.
    assert any("reviewed_by" in p for p in replay.problems(case))
    case["reviewed_by"] = "Ana"
    assert replay.problems(case) == []
    case["original"]["transcript"].append(["person", "my key is ghp_" + "a" * 30])
    assert any("secret" in p for p in replay.problems(case))
    # The shipped example is a signed, runnable case.
    assert [replay.problems(c) for c in replay.load(REPLAY / "cases")] == [[]]


class FakeTico:
    """Just enough of the API for run.py: the bot 'runs' when the task is run, as `behave` says."""

    def __init__(self, behave):
        self.behave, self.tasks, self.calls = behave, {}, []

    def request(self, method, path, body=None, token=None):
        self.calls.append((method, path))
        if path == "me":
            return 200, {"actor": "human:owner"}
        if path.endswith("/instructions"):
            return 200, {"content": "# New prompt", "published": True}
        if method == "POST" and path == "tasks":
            self.tasks["r1"] = {"task": {"id": "r1", "version": 1, "status": "open", "owner": body["owner"], **body},
                                "messages": [], "comments": [], "runs": [], "files": []}
            return 200, {"task": self.tasks["r1"]["task"]}
        tid = path.split("/")[1]
        row = self.tasks[tid]
        if path.endswith("/files"):
            if method == "POST":
                row["files"].append({"name": body["name"], "versions": [{"by": "human:owner"}]})
            return 200, {"files": row["files"]}
        if path.endswith("/comments"):
            row["comments"].append(message(f"m{len(row['comments'])}", "human:owner", body["text"], "2099-01-01T00:00:01Z"))
            return 200, {}
        if path.endswith("/run-now"):
            self.behave(row)
            return 200, {"queued": True}
        if method == "POST":
            row["task"].update({k: v for k, v in body.items() if k != "version"})
        return 200, row


def bot_finishes_well(row):
    row["runs"].append({"started": "2099-01-01T00:00:02Z", "finished": "2099-01-01T00:03:00Z"})
    row["files"].append({"name": "engineering-summary.md", "versions": [{"by": "bot:engineering-lead"}]})
    row["messages"].append(message("b1", "bot:engineering-lead", "Attached: 5 shipped, nothing broke.", "2099-01-01T00:02:00Z"))
    row["task"]["status"] = "done"


def bot_gives_up(row):
    row["runs"] += [{"started": "2099-01-01T00:00:02Z", "finished": "2099-01-01T00:03:00Z"}] * 3
    row["messages"].append(message("b1", "bot:engineering-lead", "I could not read the runners (see harness logs).",
                                   "2099-01-01T00:02:00Z"))
    row["task"]["status"] = "waiting"


@pytest.mark.parametrize("behave,verdict", [(bot_finishes_well, "win"), (bot_gives_up, "regression")])
def test_replay_scores_candidate_against_original(behave, verdict, monkeypatch, tmp_path):
    server = FakeTico(behave)
    monkeypatch.setattr(live, "Live", lambda url: server)
    monkeypatch.setattr(live.time, "sleep", lambda s: None)
    report = tmp_path / "replay.md"
    code = live.main(["--url", "http://fake", "--token", "t", "--cases", str(REPLAY / "cases"),
                      "--quiet", "0", "--timeout", "5", "--report", str(report)])

    # The opening state was built before the bot was handed the task and woken.
    order = [c for c in server.calls if c[0] == "POST"]
    assert order == [("POST", "tasks"), ("POST", "tasks/r1/files"), ("POST", "tasks/r1/comments"),
                     ("POST", "tasks/r1"), ("POST", "tasks/r1/run-now")]
    assert server.tasks["r1"]["task"]["owner"] == "bot:engineering-lead"
    text = report.read_text()
    assert f"1 case: {int(verdict == 'win')} wins, {int(verdict == 'regression')} regressions" in text
    assert code == (0 if verdict == "win" else 1)
    if verdict == "regression":
        assert "## Regressions" in text and "no longer done" in text
