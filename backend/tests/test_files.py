"""Files: visibility first (a private chat leaks nothing), versions, refusals,
S3 imports and link rules. See docs/files.md."""

import os

import pytest

from backend.tests.test_api import api, assign, claim, headers, post, ready, runner  # noqa: F401  (fixtures)
from clients import bot_files as BF


def turn(api, bot="ops", who="ben-test", machine=None):
    """A person chats with the bot and a runner claims it: (machine, the attempt with the bot's token)."""
    machine = machine or runner(api)
    assign(api, machine, bot)
    ready(api, machine, [bot])
    post(api, "chat/" + bot, {"text": "Write the plan"}, who)
    return machine, claim(api, machine, bot)


def publish(api, attempt, name="plan.md", text="# Plan", **fields):
    return api.post("/api/v2/files/uploads", json={"name": name, "text": text, **fields},
                    headers=headers(attempt["token"]))


def listing(api, bot="ops", who="ben-test"):
    r = api.get(f"/api/v2/bots/{bot}/files", headers=headers(who))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_private_chats_file_is_invisible_to_everyone_else(api):
    _, attempt = turn(api)
    made = publish(api, attempt)
    assert made.status_code == 200, made.text
    fid = made.json()["file"]["id"]
    assert listing(api)["total"] == 1
    for other in ("ana-test", "cara-test"):        # the company owner included: a personal chat is not theirs
        page = listing(api, who=other)
        assert page["total"] == 0 and page["files"] == []
        for path in ("", "/activity", "/versions", "/versions/1", "/meta"):
            assert api.get("/api/v2/files/" + fid + path, headers=headers(other)).status_code == 404, path
        assert "plan" not in api.get("/api/v2/bots/ops/files?limit=100", headers=headers(other)).text
    # Promote is the owner's or a bot administrator's, explicit and audited; then everyone who sees the bot sees it.
    assert api.patch("/api/v2/files/" + fid, json={"promote": True}, headers=headers("cara-test")).status_code == 404
    assert api.patch("/api/v2/files/" + fid, json={"promote": True}, headers=headers(attempt["token"])).status_code == 403
    assert api.patch("/api/v2/files/" + fid, json={"promote": True}, headers=headers("ben-test")).status_code == 200
    assert listing(api, who="cara-test")["total"] == 1
    assert api.get("/api/v2/files/" + fid, headers=headers("cara-test")).content == b"# Plan"
    log = api.get("/api/v2/files/" + fid + "/activity", headers=headers("cara-test")).json()["activity"]
    assert [a["action"] for a in log] == ["promoted", "created"]


def test_refusals_and_a_bot_writes_only_its_own_files(api):
    machine, attempt = turn(api, "ops")
    for name in (".env", "prod-credentials.csv", "id_rsa.txt", "tool.exe", "notes"):
        assert publish(api, attempt, name).status_code == 422, name
    assert publish(api, attempt, "x.md", path="../x.md").status_code == 422
    big = api.post("/api/v2/files/uploads?name=big.csv", content=b"x" * (BF.MAX_BYTES + 1),
                   headers={**headers(attempt["token"]), "Content-Type": "application/octet-stream"})
    assert big.status_code == 422, big.text
    assert listing(api)["total"] == 0
    # A bot cannot pick another bot's page: the authenticated identity decides.
    assign(api, machine, "finance")
    ready(api, machine, ["ops", "finance"])
    mine = publish(api, attempt, "mine.md", bot="finance", scope="bot")
    assert mine.status_code == 403                      # inside a chat: not bot-wide
    mine = publish(api, attempt, "mine.md", bot="finance").json()["file"]
    assert listing(api, "finance", "ana-test")["total"] == 0
    post(api, "chat/finance", {"text": "hello"}, "ana-test")
    other = claim(api, machine, "finance")
    assert api.patch("/api/v2/files/" + mine["id"], json={"title": "stolen"}, headers=headers(other["token"])).status_code == 404
    assert api.post("/api/v2/files/uploads", json={"name": "a.md", "text": "a"}, headers=headers("ana-test")).status_code == 403


def test_local_rules_refuse_traversal_links_env_and_oversize(tmp_path):
    root = tmp_path / "checkout"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "ok.md").write_text("fine")
    (root / "reports" / ".env").write_text("KEY=1")
    (tmp_path / "outside.md").write_text("secret")
    os.symlink(tmp_path / "outside.md", root / "reports" / "link.md")
    with open(root / "reports" / "huge.csv", "wb") as stream:
        stream.truncate(BF.MAX_BYTES + 1)
    assert BF.local_file(root, "reports/ok.md")[1] == "reports/ok.md"
    for bad in ("../outside.md", str(tmp_path / "outside.md"), "reports/../../outside.md", "reports/link.md",
                "reports/.env", "reports/huge.csv", "reports"):
        with pytest.raises(BF.Refused):
            BF.local_file(root, bad)
