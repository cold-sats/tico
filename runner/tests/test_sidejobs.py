"""The runner supervises its side jobs: start when wanted, stop when not, restart with backoff."""
import re
import subprocess
from pathlib import Path

import yaml

from runner import sidejobs
from runner.sidejobs import SideJobs

ROOT = Path(__file__).resolve().parents[2]


class Proc:
    def __init__(self):
        self.code, self.signals = None, []

    def poll(self):
        return self.code

    def terminate(self):
        self.signals.append("term")
        self.code = -15

    def kill(self):
        self.signals.append("kill")
        self.code = -9

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired("job", timeout)
        return self.code


class Hub:
    def __init__(self, sources=None):
        self.sources, self.posts = sources or [], []

    def get(self, path):
        assert path == "runners/importers"
        return {"importers": [{"source": s} for s in self.sources]}

    def post(self, path, body):
        self.posts.append((path, body))


class Rig:
    def __init__(self, hub=None, jobs=None):
        self.now, self.spawned, self.hub = 0.0, [], hub or Hub()
        self.jobs = jobs or {"importers": (sidejobs.importers_wanted, sidejobs.report_importers)}
        self.side = SideJobs({"url": "u", "token": "t", "projects_dir": "/none"}, "/x/runner.json",
                             client=self.hub, jobs=self.jobs, spawn=self.spawn, clock=lambda: self.now)

    def spawn(self, name):
        proc = Proc()
        self.spawned.append((name, proc))
        return proc


def test_starts_only_when_the_hub_assigns_it_here():
    rig = Rig(Hub([]))
    rig.side.tick()
    assert rig.spawned == []                       # another computer runs the importers
    rig.hub.sources = ["fireflies"]
    rig.side.tick()
    rig.side.tick()
    assert [n for n, _ in rig.spawned] == ["importers"]     # started once, not once per pass


def test_stops_cleanly_when_unassigned():
    rig = Rig(Hub(["zoom"]))
    rig.side.tick()
    rig.hub.sources = []
    rig.side.tick()
    assert rig.spawned[0][1].signals == ["term"]
    assert rig.side.children == {}
    rig.side.tick()
    assert len(rig.spawned) == 1


def test_a_crash_restarts_with_growing_backoff_and_reports_it():
    rig = Rig(Hub(["zoom"]))
    rig.side.tick()
    delays = []
    for _ in range(4):
        rig.spawned[-1][1].code = 1
        rig.now += 1
        before = rig.now
        rig.side.tick()                            # sees the exit; too early to restart
        delays.append(rig.side.retry_at["importers"] - before)
        rig.now = rig.side.retry_at["importers"]
        rig.side.tick()
    assert delays == [10, 20, 40, 80]
    assert len(rig.spawned) == 5
    assert rig.hub.posts[0][0] == "imports/sources/zoom/status" and rig.hub.posts[0][1]["state"] == "error"


def test_a_stable_run_resets_the_backoff_and_a_clean_exit_restarts_soon():
    rig = Rig(Hub(["zoom"]))
    rig.side.failures["importers"] = 3
    rig.side.tick()
    rig.now += sidejobs.STABLE_SECONDS + 1
    rig.spawned[-1][1].code = 1
    rig.side.tick()
    assert rig.side.retry_at["importers"] - rig.now == 10
    rig.now = rig.side.retry_at["importers"]
    rig.side.tick()
    rig.spawned[-1][1].code = 0                    # new code in the checkout: no backoff, no error report
    posts = len(rig.hub.posts)
    rig.side.tick()
    assert rig.side.retry_at["importers"] - rig.now == 5 and len(rig.hub.posts) == posts


def test_a_hub_outage_leaves_a_running_job_alone():
    rig = Rig(Hub(["zoom"]))
    rig.side.tick()
    rig.hub.get = lambda path: (_ for _ in ()).throw(OSError("down"))
    rig.side.tick()
    assert rig.spawned[0][1].signals == [] and "importers" in rig.side.children


def test_close_runs_where_its_key_is(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOSE_API_KEY", raising=False)
    (tmp_path / "secrets").mkdir()
    rig = Rig(jobs={"close-calls": (sidejobs.close_wanted, sidejobs.report_close)})
    rig.side.config["projects_dir"] = str(tmp_path)
    rig.side.tick()
    assert rig.spawned == []
    (tmp_path / "secrets/close-calls.env").write_text("CLOSE_API_KEY=k\n")
    rig.side.tick()
    assert [n for n, _ in rig.spawned] == ["close-calls"]


def test_stop_terminates_every_child():
    rig = Rig(Hub(["zoom"]))
    rig.side.tick()
    rig.side.stopping.set()
    rig.side.run()
    assert rig.spawned[0][1].signals == ["term"]


def test_a_stubborn_child_is_killed(monkeypatch):
    class Stubborn(Proc):
        def terminate(self):
            self.signals.append("term")
    rig = Rig(Hub(["zoom"]))
    rig.spawn = lambda name: rig.spawned.append((name, Stubborn())) or rig.spawned[-1][1]
    rig.side.spawn = rig.spawn
    monkeypatch.setattr(sidejobs, "STOP_GRACE", 0)
    rig.side.tick()
    rig.side.halt("importers")
    assert rig.spawned[0][1].signals == ["term", "kill"]


def test_the_child_command_is_the_runner_subcommand():
    seen = {}
    side = SideJobs({"url": "u", "token": "t"}, "/x/runner.json", client=Hub())
    import runner.sidejobs as module
    orig = module.subprocess.Popen
    module.subprocess.Popen = lambda cmd, **kw: seen.update(cmd=cmd, env=kw["env"])
    try:
        side.popen("importers")
    finally:
        module.subprocess.Popen = orig
    assert seen["cmd"][1:] == ["-m", "runner", "--config", "/x/runner.json", "importers"]
    assert "TICO_SIDE_JOBS" not in seen["env"]


def test_compose_turns_it_on_without_extra_services():
    compose = yaml.safe_load((ROOT / "docker/runner.compose.yaml").read_text())
    # The runner supervises its side jobs; the only other service is the release updater.
    assert list(compose["services"]) == ["runner", "updater"]
    assert "runner-home:/home/runner" in compose["services"]["runner"]["volumes"]
    entry = (ROOT / "docker/runner-entrypoint.sh").read_text()
    assert re.search(r'export TICO_SIDE_JOBS="\$\{TICO_SIDE_JOBS:-1\}"', entry)
    assert entry.index("TICO_SIDE_JOBS") < entry.index("exec python -m runner")


class Connectors:
    """A hub that may or may not name this computer's operator a processing operator."""
    def __init__(self, assigned=(), status=0):
        self.assigned, self.status = list(assigned), status

    def get(self, path):
        assert path == "runners/connectors"
        if self.status:
            from clients.tico import APIError
            raise APIError("not_found", "no such route", status=self.status)
        return {"connectors": self.assigned}

    def post(self, path, body):
        pass


def connectors_rig(tmp_path, hub):
    rig = Rig(hub, jobs={"connectors": (sidejobs.connectors_wanted, sidejobs.report_connectors)})
    rig.side.config["projects_dir"] = str(tmp_path)
    (tmp_path / "secrets").mkdir(exist_ok=True)
    return rig


def test_connectors_run_where_the_google_key_is_even_when_the_hub_names_no_one(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SA_KEY", raising=False)
    rig = connectors_rig(tmp_path, Connectors())
    rig.side.tick()
    assert rig.spawned == []
    (tmp_path / "secrets/google-sa.json").write_text("{}")
    rig.side.tick()
    rig.side.tick()
    assert [n for n, _ in rig.spawned] == ["connectors"]
    (tmp_path / "secrets/google-sa.json").unlink()
    rig.side.tick()
    assert rig.spawned[0][1].signals == ["term"]             # the key left this computer


def test_connectors_run_where_the_hub_assigns_them_and_an_old_hub_only_counts_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SA_KEY", raising=False)
    rig = connectors_rig(tmp_path, Connectors(["mail", "calendar"]))
    rig.side.tick()
    assert [n for n, _ in rig.spawned] == ["connectors"]
    old = connectors_rig(tmp_path, Connectors(status=404))
    old.side.tick()
    assert old.spawned == []


def test_google_sa_key_names_the_key_anywhere(tmp_path, monkeypatch):
    key = tmp_path / "elsewhere.json"
    key.write_text("{}")
    monkeypatch.setenv("GOOGLE_SA_KEY", str(key))
    rig = connectors_rig(tmp_path, Connectors())
    rig.side.tick()
    assert [n for n, _ in rig.spawned] == ["connectors"]


def test_the_linux_runner_names_where_the_connectors_look():
    entry = (ROOT / "docker/runner-entrypoint.sh").read_text()
    assert 'export TICO_PROJECTS_DIR="${TICO_PROJECTS_DIR:-$HOME/workspace}"' in entry
    assert "TICO_MAIL_VENV" in entry and entry.index("TICO_MAIL_VENV") < entry.index("exec python -m runner")
