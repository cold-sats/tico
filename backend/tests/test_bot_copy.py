"""Copy a bot and copy a skill, done by BotOps as the person who asked (backend/bot_copy.py, clients/botcopy.py).

Ana owns the company, Ben is an admin, Cara is a member (the base fixture). A copy is an ordinary bot its requester owns; the
server decides and records, BotOps's computer moves the files.
"""
import base64
import json
import subprocess

import pytest

from backend import hubdb as H
from backend.credentials import effective_grant
from backend.tests.test_api import api, as_member, get, headers, post, restrict  # noqa: F401  (fixture)
from backend.tests.test_botops_parity import act
from backend.tests.test_credential_sharing import jira, local
from backend.tests.test_member_bots import botops, call, turn  # noqa: F401  (fixture)
from clients import botcopy, hubtools
from clients.tico import APIError

SHA = "a" * 40


@pytest.fixture
def scribe(api):
    """Ana's bot, open to everyone to read and write."""
    return post(api, "bots", {"slug": "scribe", "display_name": "Scribe", "description": "Takes meeting notes", "status": "planned",
                              "model": "gpt-6-astra", "effort": "high", "harness": None, "runner_id": None})


def copy(api, body=None, token="cara-test", bot="scribe", expected=200):
    r = api.post(f"/api/v2/bots/{bot}/copy", json={"sha": SHA, **(body or {})}, headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


def config_of(api, slug):
    with api.app.state.store.read() as c:
        row = c.execute("SELECT * FROM bot_config WHERE bot=?", (slug,)).fetchone()
        return dict(row), json.loads(row["config_json"])


# ------------------------------------------------------------------ the copy
def test_a_copy_is_an_independent_bot_owned_by_whoever_asked(api, scribe):
    made = copy(api, {"slug": "cara-scribe", "display_name": "Cara's Scribe"})
    assert made["slug"] == "cara-scribe" and made["status"] == "planned" and made["bot_owners"] == ["cara"]
    assert made["repo"] == "bot-cara-scribe" and made["copied_from"] == {"bot": "scribe", "sha": SHA}
    row, config = config_of(api, "cara-scribe")
    assert (row["created_by"], row["operator"], row["reports_to"]) == ("human:cara", "cara", "human:cara")
    assert row["description"] == "Takes meeting notes" and config["copied_from"] == {"bot": "scribe", "sha": SHA}
    assert (config["model"], config["reasoning_effort"]) == ("gpt-6-astra", "high")         # the original's model settings
    # Nothing is linked: the original is as it was, and the copy is a bot of its own (its owner may change it, Ana's original she may not).
    assert config_of(api, "scribe")[0]["operator"] == "ana" and "copied_from" not in config_of(api, "scribe")[1]
    current = get(api, "bots", "cara-test")
    revision = next(b for b in current if b["slug"] == "cara-scribe")["revision"]
    assert post(api, "bots/cara-scribe/definition", {"display_name": "Renamed", "expected_revision": revision}, "cara-test")
    post(api, "bots/scribe/definition", {"display_name": "Mine", "expected_revision": 1}, "cara-test", expected=403)
    with api.app.state.store.read() as c:
        event = c.execute("SELECT actor,detail_json FROM events WHERE action='bot.copied'").fetchone()
        assert event["actor"] == "human:cara" and json.loads(event["detail_json"])["from"] == "scribe"
    # Left out, the slug and the name follow the original; asking again makes another.
    again = copy(api)
    assert again["slug"] == "scribe-copy" and again["display_name"] == "Copy of Scribe" and copy(api)["slug"] == "scribe-copy-2"
    copy(api, {"slug": "cara-scribe"}, expected=409)                                            # a slug someone holds


def test_a_model_the_company_no_longer_offers_is_replaced_by_the_team_default(api, scribe):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET model='retired-model' WHERE slug='scribe'")
        c.execute("UPDATE bot_config SET config_json=json_set(config_json,'$.model','retired-model') WHERE bot='scribe'")
    made = copy(api)
    fresh = post(api, "bots/register", {"slug": "fresh"}, "cara-test")
    assert made["model"] == fresh["model"] != "retired-model"


def test_who_may_copy_what_and_how_many(api, botops, scribe):
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", see={"everyone": True}, read={"people": ["ana"]}, write={"people": ["ana"]})
    # Cara may see it but not read it: read is the right a copy needs.
    assert copy(api, expected=403)["error"]["code"] == "forbidden"
    copy(api, token="ben-test", expected=200)                                                    # an admin reads every bot
    restrict_open = {"see": {"everyone": True}, "read": {"everyone": True}, "write": {"everyone": True}}
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", **restrict_open)
    copy(api, {"slug": "botops-copy"}, bot="botops", expected=409)                                # the company's own bots are not copied
    copy(api, bot="nobody", expected=404)
    # It counts toward the requester's limit like any bot they add; a member switched off from adding bots may not copy.
    assert call(api, "put", "access/limits", "ben-test", {"member_bot_limit": 1}).status_code == 200
    copy(api)
    assert copy(api, expected=409)["error"]["code"] == "bot_limit"
    assert call(api, "post", "access/people/cara", "ben-test", {"create_bots": False}).status_code == 200
    copy(api, expected=403)


def test_a_credential_the_original_holds_is_granted_only_by_a_credential_administrator(api, scribe):
    local(api)
    stored = jira(api)
    post(api, f"credentials/{stored['id']}/grants", {"subject": "bot:scribe"})
    tools = [{"service": "jira", "env": "JIRA_BASIC_AUTH"}, {"service": "zoom", "env": "ZOOM_TOKEN"}]
    by_ben = copy(api, {"slug": "ben-scribe", "tools": tools}, token="ben-test")["credentials"]
    assert [(g["env"], g["credential"]) for g in by_ben["granted"]] == [("JIRA_BASIC_AUTH", "Jira")]
    assert [n["needs"] for n in by_ben["needs"]] == ["needs credential ZOOM_TOKEN"]              # the original has none stored
    with api.app.state.store.read() as c:
        assert effective_grant(c, stored["id"], "bot:ben-scribe") and not effective_grant(c, stored["id"], "bot:ben-scribe-2")
    # A member is told who can: nothing is granted, and no value moves.
    by_cara = copy(api, {"slug": "cara-scribe", "tools": tools})["credentials"]
    assert by_cara["granted"] == [] and [n["env"] for n in by_cara["needs"]] == ["JIRA_BASIC_AUTH", "ZOOM_TOKEN"]
    assert "credential administrator" in by_cara["needs"][0]["detail"] and "hunter" not in json.dumps(by_cara)
    with api.app.state.store.read() as c:
        assert not effective_grant(c, stored["id"], "bot:cara-scribe")


# ------------------------------------------------------------------ update from the original, and suggesting back
def test_a_copy_knows_what_it_was_copied_from_and_only_its_owner_updates_it(api, scribe):
    post(api, "bots/scribe/update-from-original", {}, "ana-test", expected=409)                   # not a copy
    copy(api, {"slug": "cara-scribe"})
    plan = post(api, "bots/cara-scribe/update-from-original", {}, "cara-test")
    assert (plan["original"], plan["base_sha"], plan["repo"]) == ("scribe", SHA, "bot-cara-scribe")
    post(api, "bots/cara-scribe/update-from-original", {}, "ben-test")                            # an admin manages it
    as_member(api, "ben@acme.example")
    post(api, "bots/cara-scribe/update-from-original", {}, "ben-test", expected=403)              # a stranger does not
    # A merged copy is now up to date with the original's newer commit, and the record says so.
    newer = "b" * 40
    done = post(api, "bots/cara-scribe/update-from-original", {"applied_sha": newer}, "cara-test")
    assert done["base_sha"] == newer and config_of(api, "cara-scribe")[1]["copied_from"] == {"bot": "scribe", "sha": newer}
    post(api, "bots/cara-scribe/update-from-original", {"applied_sha": "nope"}, "cara-test", expected=422)


class GitHub:
    """What the GitHub App is asked to do, recorded, for one repository."""
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, **kw):
        self.calls.append((method, path, kw.get("json")))

        class Answer:
            status_code, content = 200, b"{}"

            def json(self_):
                return self_.body
        answer = Answer()
        answer.body = {}
        if path == "/repos/Acme/bot-scribe":
            answer.body = {"default_branch": "main"}
        elif path.endswith("/git/ref/heads/main"):
            answer.body = {"object": {"sha": "f" * 40}}
        elif method == "GET" and path.endswith("/contents/AGENT.md"):
            answer.body = {"sha": "old-sha"}
        elif method == "GET":
            answer.status_code = 404
        elif path.endswith("/git/refs"):
            answer.status_code = 201
        elif path.endswith("/pulls"):
            answer.status_code, answer.body = 201, {"html_url": "https://github.com/Acme/bot-scribe/pull/7"}
        elif method == "PUT" and "/contents/" in path and "sha" not in (kw.get("json") or {}):
            answer.status_code = 201
        return answer


def suggestion(**more):
    return {"files": [{"path": "AGENT.md", "content": "# Scribe, better\n"}, {"path": "skills/triage/SKILL.md", "content": "Triage.\n"}],
            "diff": "-old\n+new\n", "held_back": ["playbooks/x.md"], **more}


def test_a_suggestion_is_a_pull_request_when_the_requester_may_write_else_a_task_for_the_owner(api, scribe, monkeypatch):
    copy(api, {"slug": "cara-scribe"})
    github, service = GitHub(), api.app.state.github_app
    monkeypatch.setattr(service, "row", lambda c=None: {"org": "Acme", "administration": 1})
    monkeypatch.setattr(service, "mint", lambda repos, permissions: ("ghs_token", "later"))
    monkeypatch.setattr(service, "_call", lambda method, path, **kw: github(method, path, **kw))
    made = post(api, "bots/cara-scribe/suggest-to-original", suggestion(title="Better triage"), "cara-test")
    assert made["how"] == "pull_request" and made["url"].endswith("/pull/7") and made["files"] == ["AGENT.md", "skills/triage/SKILL.md"]
    sent = {(m, p.rsplit("/", 1)[-1]): body for m, p, body in github.calls if body}
    assert sent[("POST", "refs")]["ref"].startswith("refs/heads/tico/suggest-cara-scribe-") and sent[("POST", "refs")]["sha"] == "f" * 40
    agent = next(body for m, p, body in github.calls if m == "PUT" and p.endswith("/contents/AGENT.md"))
    assert base64.b64decode(agent["content"]) == b"# Scribe, better\n" and agent["sha"] == "old-sha"     # an existing file is updated
    pull = sent[("POST", "pulls")]
    assert pull["title"] == "Better triage" and pull["base"] == "main" and "playbooks/x.md" in pull["body"] and "+new" in pull["body"]
    assert not any("hunter" in json.dumps(body) for _, _, body in github.calls if body)
    # Without write access to the original the owner gets the diff as a task instead, and nothing reaches GitHub.
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", see={"everyone": True}, read={"everyone": True}, write={"people": ["ana"]})
    before = len(github.calls)
    asked = post(api, "bots/cara-scribe/suggest-to-original", suggestion(), "cara-test")
    assert asked["how"] == "task" and "may not write" in asked["detail"] and len(github.calls) == before
    with api.app.state.store.read() as c:
        task = H.task(c, asked["task_id"])
    assert task["owner"] == "human:ana" and task["requester"] == "human:cara" and "+new" in task["body"] and "AGENT.md" in task["body"]
    # Only instructions, and only by someone who manages the copy.
    post(api, "bots/cara-scribe/suggest-to-original", {"files": [{"path": ".env", "content": "x"}]}, "cara-test", expected=422)
    post(api, "bots/cara-scribe/suggest-to-original", {"files": [{"path": "reports/a.md", "content": "x"}]}, "cara-test", expected=422)
    post(api, "bots/cara-scribe/suggest-to-original", suggestion(), "ben-test")
    as_member(api, "ben@acme.example")
    post(api, "bots/cara-scribe/suggest-to-original", suggestion(), "ben-test", expected=403)


# ------------------------------------------------------------------ a skill
def test_a_skill_is_copied_only_to_bots_the_requester_manages_and_reads_from_a_bot_they_read(api, scribe):
    copy(api, {"slug": "cara-scribe"})
    body = {"skill": "triage", "to": ["cara-scribe"]}
    assert post(api, "bots/scribe/skills/copy", body, "cara-test") == {
        "skill": "triage", "from": "scribe", "to": [{"bot": "cara-scribe", "repo": "bot-cara-scribe"}]}
    post(api, "bots/scribe/skills/copy", {"skill": "triage", "to": ["ops"]}, "cara-test", expected=403)        # not hers to change
    post(api, "bots/scribe/skills/copy", {"skill": "triage", "to": ["scribe"]}, "cara-test", expected=422)
    post(api, "bots/scribe/skills/copy", {"skill": "../x", "to": ["cara-scribe"]}, "cara-test", expected=422)
    post(api, "bots/scribe/skills/copy", {"skill": "triage", "to": ["ghost"]}, "cara-test", expected=404)
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", people=["ana"])
    post(api, "bots/scribe/skills/copy", body, "cara-test", expected=404)                                     # she cannot even see it
    assert post(api, "bots/scribe/skills/copy", {"skill": "triage", "to": ["cara-scribe", "ops"]}, "ana-test")["to"][1]["bot"] == "ops"


# ------------------------------------------------------------------ BotOps, as the requester
def test_botops_copies_as_the_person_who_asked_and_never_as_itself(api, botops, scribe):
    attempt = turn(api, botops, text="Make me my own copy of the scribe")
    made = act(api, attempt, "POST", "bots/scribe/copy", {"slug": "cara-scribe", "sha": SHA})
    assert made.status_code == 200, made.text
    row, config = config_of(api, "cara-scribe")
    assert (row["created_by"], row["operator"]) == ("human:cara", "cara") and config["copied_from"]["bot"] == "scribe"
    with api.app.state.store.read() as c:
        for action in ("bot.definition_created", "bot.copied"):
            event = c.execute("SELECT actor,detail_json FROM events WHERE action=? AND target='cara-scribe'", (action,)).fetchone()
            assert event["actor"] == "human:cara" and '"via": "botops"' in event["detail_json"]
    # Both explicit and default requester rights enforce her source Read check.
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", people=["ana"])
    assert act(api, attempt, "POST", "bots/scribe/copy", {"slug": "again", "sha": SHA}).status_code == 404
    assert call(api, "post", "bots/scribe/copy", attempt["token"], {"sha": SHA}).status_code == 404          # Default requester rights also enforce the source Read check


class Hub:
    """The `api` the tools call, as BotOps's runner makes it: its own token, and the requester's header when acting for a person."""
    def __init__(self, api, token):
        self.api, self.token = api, token

    def call(self, method, path, body=None, key=None, query=None, delegate=False):
        head = {**headers(self.token, key), **({"X-Tico-On-Behalf-Of": "turn"} if delegate else {})}
        r = self.api.request(method, "/api/v2/" + path, json=body, params=query, headers=head)
        if r.status_code >= 400:
            error = r.json()["error"]
            raise APIError(error["code"], error["detail"], r.status_code)
        return r.json()

    def get(self, path, **query):
        return self.call("GET", path, query=query)

    def post(self, path, body=None, key=None):
        return self.call("POST", path, body if body is not None else {}, key)


def git(path, *argv):
    return subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *argv],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_the_tools_copy_update_and_share_a_skill_in_the_workspace_as_the_requester(api, botops, scribe, monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    original = workspace / "bot-scribe"
    original.mkdir(parents=True)
    git(original, "init", "-q", "-b", "main")
    files = {"AGENT.md": "# Scribe\n\n## Owns\n- Notes\n\nOne.\nTwo.\nThree.\nFour.\nFive.\n", "state.md": "# State\nprivate\n",
             "bot.yaml": "name: scribe\ndisplay_name: Scribe\nlabels: [owner:scribe]\ntools:\n  - service: jira\n    can: [read]\n    env: JIRA_BASIC_AUTH\n",
             "skills/triage/SKILL.md": "Triage.\n", ".env": "JIRA_BASIC_AUTH=hunter2\n"}
    for rel, text in files.items():
        (original / rel).parent.mkdir(parents=True, exist_ok=True)
        (original / rel).write_text(text)
    git(original, "add", "-A")
    git(original, "commit", "-q", "-m", "Start")
    monkeypatch.setenv("HUB_WORKSPACE", str(workspace))
    attempt = turn(api, botops, text="Copy the scribe for me, and bring it up to date later")
    hub = Hub(api, attempt["token"])
    def tool(tool_name, **args):
        return hubtools.BY_NAME[tool_name]["fn"](hub, args)

    made = tool("hub_bot_copy", bot="scribe", slug="cara-scribe", name="Cara's Scribe")
    assert made["slug"] == "cara-scribe" and made["copied_from"] == {"bot": "scribe", "sha": git(original, "rev-parse", "HEAD")}
    assert [n["needs"] for n in made["credentials"]["needs"]] == ["needs credential JIRA_BASIC_AUTH"]
    assert made["published"] is False and "Only the owner" in made["reason"]              # no GitHub here: it stays on this computer
    copy_dir = workspace / "bot-cara-scribe"
    assert git(copy_dir, "log", "--format=%s") == f"Copied from scribe at {made['from_sha'][:12]}"
    assert not (copy_dir / ".env").exists() and "private" not in (copy_dir / "state.md").read_text()
    assert config_of(api, "cara-scribe")[0]["created_by"] == "human:cara"

    # The original moves on; bringing the copy up to date is its own request, and the server remembers where it is now.
    (original / "AGENT.md").write_text(files["AGENT.md"].replace("Two.", "Two, better."))
    git(original, "commit", "-qam", "Better")
    (copy_dir / "AGENT.md").write_text(files["AGENT.md"].replace("Five.", "Five, mine."))
    git(copy_dir, "commit", "-qam", "Mine")
    updated = tool("hub_bot_update_from_original", bot="cara-scribe")
    assert updated["status"] == "updated" and updated["updated"] == ["AGENT.md"]
    merged = (copy_dir / "AGENT.md").read_text()
    assert "Two, better." in merged and "Five, mine." in merged
    assert config_of(api, "cara-scribe")[1]["copied_from"]["sha"] == git(original, "rev-parse", "HEAD")
    assert tool("hub_bot_update_from_original", bot="cara-scribe")["status"] == "current"

    # No GitHub and no write on the original: the suggestion is a task for its owner.
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", see={"everyone": True}, read={"everyone": True}, write={"people": ["ana"]})
    suggested = tool("hub_bot_suggest_to_original", bot="cara-scribe")
    assert suggested["how"] == "task" and suggested["files"] == ["AGENT.md"]
    assert tool("hub_bot_suggest_to_original", bot="cara-scribe", paths=["skills"])["suggested"] is False

    # A skill goes to a bot she manages; one she does not is refused before any file moves.
    second = tool("hub_bot_copy", bot="cara-scribe", slug="cara-helper")
    (workspace / "bot-cara-scribe" / "skills" / "minutes").mkdir()
    (workspace / "bot-cara-scribe" / "skills" / "minutes" / "SKILL.md").write_text("Minutes.\n")
    git(workspace / "bot-cara-scribe", "add", "-A")
    git(workspace / "bot-cara-scribe", "commit", "-qm", "A skill")
    shared = tool("hub_skill_copy", skill="minutes", bot="cara-scribe", to=["cara-helper"])
    assert [(r["bot"], r["status"]) for r in shared["to"]] == [("cara-helper", "copied")] and second["slug"] == "cara-helper"
    assert (workspace / "bot-cara-helper" / "skills" / "minutes" / "SKILL.md").read_text() == "Minutes.\n"
    assert git(workspace / "bot-cara-helper", "log", "-1", "--format=%s") == "Copy the minutes skill from cara-scribe"
    with pytest.raises(APIError) as refused:
        tool("hub_skill_copy", skill="triage", bot="scribe", to=["ops"])
    assert refused.value.status == 403 and not (workspace / "bot-ops").exists()
    assert botcopy.head(workspace / "bot-cara-helper") and "botops" in hubtools.offered_to(hubtools.BY_NAME["hub_bot_copy"])
    assert "hub_bot_copy" in {t["name"] for t in hubtools.listing(local=True)} and "hub_bot_copy" not in {t["name"] for t in hubtools.listing()}


def test_botops_is_given_a_read_only_token_for_a_bot_on_another_computer_only_for_a_person_who_may_read_it(api, botops, scribe, monkeypatch, tmp_path):
    service, minted = api.app.state.github_app, []
    attempt = turn(api, botops, text="Copy the scribe")
    token = lambda who="botops": act(api, attempt, "POST", "bots/scribe/repository-read-token", {})
    assert token().json() == {"configured": False}                                   # GitHub is not connected: nothing to fetch
    monkeypatch.setattr(service, "row", lambda c=None: {"org": "Acme", "administration": 1})
    monkeypatch.setattr(service, "mint", lambda repos, permissions: minted.append((repos, permissions)) or ("ghs_read", "later"))
    granted = token().json()
    assert granted == {"configured": True, "token": "ghs_read", "expires_at": "later", "repository": "Acme/bot-scribe"}
    assert minted == [(["Acme/bot-scribe"], {"contents": "read", "metadata": "read"})]          # one repository, read only
    # Not a person's own call, and not for a bot the requester may not read.
    assert api.post("/api/v2/bots/scribe/repository-read-token", json={}, headers=headers("cara-test")).status_code == 403
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", people=["ana"])
    assert token().status_code == 404 and len(minted) == 1
    # The client clones with it (the runner's own clone, mocked) into a temporary folder, and says so when it cannot.
    with api.app.state.store.transaction() as c:
        restrict(c, "scribe", see={"everyone": True}, read={"everyone": True}, write={"everyone": True})
    seen = []
    import runner.git_credentials as credentials
    monkeypatch.setattr(credentials, "clone_repository", lambda path, repository, env=None, url=None: seen.append((repository, env["GH_TOKEN"])) or ("failed", "no"))
    with pytest.raises(botcopy.CopyError) as refused:
        botcopy.fetch_repository(botcopy_person(api, attempt), "scribe", tmp_path / "into")
    assert seen == [("Acme/bot-scribe", "ghs_read")] and "ask its owner to publish it" in refused.value.detail


def botcopy_person(api, attempt):
    from clients.hubtools import _Requester
    return _Requester(Hub(api, attempt["token"]))
