"""What a bot itself reads through the `hub` CLI: the org chart with each bot's reports_to and department, and the
daily and weekly updates. Runs the real CLI against a live server, as the bot."""

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path

from backend import bot_access as A
from backend import updates
from backend.tests.test_api import api, setup_attempt  # noqa: F401
from backend.tests.test_runner import live  # noqa: F401
from clients import hubcli


def hub(live, token, *argv):
    """`hub <argv>` as a bot in a turn: (exit code, parsed JSON output)."""
    env = {"HUB_API_URL": live, "HUB_TOKEN": token}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            code = hubcli.main(list(argv))
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return code, json.loads(out.getvalue())


def test_a_bot_sees_the_other_bots_with_reports_to_and_department_except_those_it_may_not_see(api, live):
    _, _, attempt = setup_attempt(api, "ops")
    hidden = A.stored({"see": A.audience({"people": ["ana"]}), "read": A.audience({"people": ["ana"]}),
                       "write": A.audience({"people": ["ana"]})})
    with api.app.state.store.transaction() as c:
        for slug, boss, template in (("cpo", "human:ana", "support-lead"), ("ops", "cpo", "support"),
                                     ("finance", "cpo", None), ("doc-updater", "cpo", None),
                                     ("product-design", "doc-updater", None), ("coo", "human:ana", None)):
            c.execute("UPDATE bot_config SET reports_to=?, config_json=json_set(config_json, '$.template', ?) WHERE bot=?",
                      (boss, template, slug))
        c.execute("UPDATE bot_config SET access_json=? WHERE bot='doc-updater'", (hidden,))

    code, org = hub(live, attempt["token"], "org")
    assert code == 0
    bots = {b["id"]: b for b in org["bots"]}
    assert set(bots) == {"coo", "ops", "cpo", "product-design", "finance"}, "everything but the bot it may not see"
    assert [bots[b]["reports_to"] for b in ("cpo", "ops", "finance")] == ["human:ana", "cpo", "cpo"]
    assert bots["cpo"]["department"] == bots["ops"]["department"] == "Customer Support", "its template's department"
    assert bots["finance"]["department"] == "Customer Support", "no template: its manager's department"
    assert bots["coo"]["department"] == "", "a bot in no department says so"
    assert (bots["ops"]["template"], bots["finance"]["template"]) == ("support", "")
    assert bots["product-design"]["reports_to"] == "cpo" and bots["product-design"]["org_parent"] == "b:cpo", \
        "under the hidden bot's manager, not dropped"
    assert {p["id"] for p in org["people"]} == {"ana", "ben", "cara"}


def test_a_bot_reads_daily_and_weekly_updates_and_one_update_in_full(api, live):
    _, _, attempt = setup_attempt(api, "ops")
    with api.app.state.store.transaction() as c:
        daily = updates.post(c, "cpo", "- Shipped the pricing page", kind="daily", day="2026-09-28")
        weekly = updates.post(c, "finance", "- Closed the books for September", kind="weekly", day="2026-09-25")
    token = attempt["token"]

    code, listed = hub(live, token, "updates", "--kind", "weekly")
    assert code == 0 and [u["id"] for u in listed["updates"]] == [weekly["id"]]
    code, listed = hub(live, token, "updates", "--kind", "daily")
    assert code == 0 and [u["id"] for u in listed["updates"]] == [daily["id"]]
    code, both = hub(live, token, "update", "list", "--bot", "finance", "--limit", "5")       # the same read, spelled like the group
    assert code == 0 and [u["id"] for u in both["updates"]] == [weekly["id"]]
    code, one = hub(live, token, "update", "show", daily["id"])
    assert code == 0 and one["update"]["headline"] == "Shipped the pricing page"
    # A bot may not mark updates read or reply: that is a person's, and the refusal says so (it is not "unsupported").
    code, refused = hub(live, token, "update", "read", daily["id"])
    assert code == 2 and refused["error"] != "unsupported" and "person" in refused["detail"]
