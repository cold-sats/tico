"""First run builds a team: the local chooser, and a starter bot's life from Create to onboarded.

The chooser runs on the catalog this release ships, so a card that loses a `pains` phrase or a
prerequisite fails here. Creating uses the real support and Chief of Staff templates.
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import yaml

from backend import onboarding as O
from backend import releases
from backend.store import H
from backend.tests.test_api import claim, headers, post, ready
from backend.tests.test_onboarding import (ASSISTANT_AGENT, ASSISTANT_CARD, BOTOPS_CARD, as_person, draft,  # noqa: F401
                                           environment, machine, signed_in)

CATALOG = Path(__file__).resolve().parents[2] / "templates" / "catalog"
CARDS = O.read_cards(SimpleNamespace(catalog_dir=CATALOG))


def answers(**said):
    return {**O.EMPTY_ANSWERS, **said}


def test_the_chooser_offers_a_small_starter_team_and_a_full_org_chart():
    """Pains, ticked tools and the sale decide both starting points; the starter team stays near five."""
    said = answers(pains=["support inbox is overflowing"], tools=["mail", "docs"], customers="consumers")
    team, held = O.choose(CARDS, said)
    assert [row["template"] for row in team] == ["support", "chief-of-staff"]
    assert team[0]["matched_pain"] == "support inbox is overflowing" and "support inbox is overflowing" in team[0]["why"]
    assert {row["tool"]: row["met"] for row in team[0]["prerequisites"]}["mail"] is True

    # Free text works too, and a ticked GitHub or meetings tool names its starter outright.
    said = answers(pains_text="we lose track of what was decided in meetings and issues pile up",
                   tools=["meetings", "github", "mail", "crm"], customers="businesses", software_product="yes")
    team, _ = O.choose(CARDS, said)
    assert {row["template"] for row in team} == {"meeting-notes", "issue-triage", "chief-of-staff"}
    # A pain with no tool to serve it is held back, never proposed: an inbox bot with no mailbox to read.
    team, held = O.choose(CARDS, answers(pains_text="email is out of control"))
    assert [row["template"] for row in team] == ["chief-of-staff"]
    assert held[0]["template"] == "inbox" and held[0]["needs"] == ["mail"]

    # The starter team is about five whatever is ticked; the full chart is everything that fits.
    everything = answers(pains=[p["text"] for p in O.pain_options(CARDS)], tools=["mail", "chat", "crm", "github", "meetings", "docs"],
                         customers="both", software_product="yes")
    team, _ = O.choose(CARDS, everything)
    assert len(team) <= O.STARTER_TEAM_MAX and "chief-of-staff" in [row["template"] for row in team]
    chart = O.full_chart(CARDS, everything, "human:morgan")
    grouped = {row["team"]: [m["template"] for m in row["members"]] for row in chart["teams"]}
    assert list(grouped) == ["Leadership", "Sales", "Marketing", "Support", "Operations", "Engineering"]
    assert sum(map(len, grouped.values())) > len(team) and grouped["Engineering"] == ["issue-triage"]
    leaders = {row["team"]: row["lead"] for row in chart["teams"]}
    assert leaders["Leadership"] == "chief-of-staff" and leaders["Marketing"] in grouped["Marketing"]
    reports = {m["slug"]: m["reports_to"] for row in chart["teams"] for m in row["members"]}
    assert reports["chief-of-staff"] == "human:morgan" and reports["mail-drafts" if "mail-drafts" in reports else "inbox"] == "chief-of-staff"
    assert len({r for r in reports.values() if r.startswith("human:")}) == 1          # every lead reports to the owner
    assert len(O.full_chart(CARDS, answers(), "human:morgan")["teams"]) == 1          # no answers: Chief of Staff only


def real_starters(api, *names):
    """The support and Chief of Staff templates as shipped: their card, playbooks and paused routine."""
    for name in names:
        shutil.copytree(CATALOG / name, Path(api.app.state.store.settings.catalog_dir) / name, dirs_exist_ok=True)


def test_a_starter_is_created_parked_and_leaves_that_state_only_when_it_says_a_person_approved(environment):
    """Create, parked, woken only by a person, onboarded by the bot itself; and the member limit ignores parked bots."""
    api = environment(cards=[(ASSISTANT_CARD, ASSISTANT_AGENT), (BOTOPS_CARD, "")])
    real_starters(api, "support", "chief-of-staff", "sales")
    computer = machine(api)
    who = signed_in()
    selected = {"chief-of-staff": {"template": "chief-of-staff", "display_name": "Chief of Staff", "instructions": ""},
                "support": {"template": "support", "display_name": "Help desk", "instructions": "",
                            "reports_to": "chief-of-staff"}}
    assert draft(api, selected=selected).status_code == 200
    record = api.post("/api/v2/onboarding/complete", json={}, headers=who).json()
    rows = {row["slug"]: row for row in record["bots"]}
    assert rows["support"]["onboarding_state"] == rows["chief-of-staff"]["onboarding_state"] == "needs_onboarding"
    assert rows["botops"]["onboarding_state"] == rows["coo"]["onboarding_state"] == ""          # built in: they work at once
    assert rows["support"]["setup_task_id"] is None and rows["support"]["reports_to"] == "chief-of-staff"
    assert rows["chief-of-staff"]["reports_to"] == "human:morgan"                              # the owner, by default

    # Exposed with the template and its version; placed on the computer and active, its routine paused.
    listed = {b["slug"]: b for b in api.get("/api/v2/bots", headers=who).json()}
    assert listed["support"]["onboarding_state"] == "needs_onboarding" and listed["coo"]["onboarding_state"] == ""
    detail = api.get("/api/v2/bots/support", headers=who).json()
    assert (detail["template"], detail["template_version"], detail["state"]) == ("support", releases.version(), "active")
    assert api.get("/api/v2/tasks", params={"owner": "botops"}, headers=who).json()["tasks"] == []   # no BotOps task
    with api.app.state.store.read() as c:
        assert c.execute("SELECT enabled FROM schedule_config sc JOIN schedules s ON s.id=sc.schedule_id "
                         "WHERE s.bot='support'").fetchone()[0] == 0
        assert json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='support'").fetchone()[0])["materialize"] is True

    # Nothing wakes it but a person: a task notice waits, the person's own message is claimed.
    ready(api, computer, ["support"])
    api.post("/api/v2/tasks", json={"owner": "support", "title": "Look at the queue", "body": "x"}, headers=signed_in())
    assert claim(api, computer, "support") is None
    post(api, "chat/support", {"text": "Let's set you up."}, token="local-owner-secret-token-0123456789")
    attempt = claim(api, computer, "support")
    assert attempt and attempt["bot"] == "support"

    # Only the bot itself (or its manager) says it is onboarded, and saying it twice changes nothing.
    def call(token):
        return api.post("/api/v2/bots/support/onboarded", json={}, headers=headers(token))
    assert call(computer["token"]).status_code == 403                 # the computer is not the bot
    said = call(attempt["token"])                                      # the bot, in its own turn
    assert said.status_code == 200 and said.json() == {"bot": "support", "onboarding_state": "onboarded", "changed": True}
    assert call(attempt["token"]).json()["changed"] is False
    assert api.get("/api/v2/bots/support", headers=who).json()["onboarding_state"] == "onboarded"
    assert api.get("/api/v2/bots/chief-of-staff", headers=who).json()["onboarding_state"] == "needs_onboarding"

    # Parked bots do not count toward a member's limit until they are onboarded.
    real_starters(api, "sales")
    assert api.put("/api/v2/access/limits", json={"member_bot_limit": 1}, headers=signed_in()).status_code == 200
    as_person(api, "quinn")
    model = api.get("/api/v2/models", headers=signed_in()).json()["default"]

    def quinn():
        return signed_in("quinn")

    def create(slug, template=""):
        return api.post("/api/v2/bots", headers=quinn(), json={
            "slug": slug, "display_name": slug, "model": model["model"], "effort": "medium", "template": template})

    for slug, template in (("help", "support"), ("closer", "sales"), ("chief-two", "chief-of-staff")):
        assert create(slug, template).status_code == 200, slug           # parked: three of them, with a limit of one
    assert create("plain").status_code == 200                              # and the one that counts still fits
    over = create("plain-two")
    assert over.status_code == 409 and over.json()["error"]["code"] == "bot_limit"

    # Onboarding one of them makes it count, so it is refused while the limit is full.
    refused = api.post("/api/v2/bots/help/onboarded", json={}, headers=quinn())
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "bot_limit"
    plain = api.get("/api/v2/bots/plain", headers=quinn()).json()
    assert api.post("/api/v2/bots/plain/archive", headers=quinn(), json={"expected_revision": plain["revision"]}).status_code == 200
    assert api.post("/api/v2/bots/help/onboarded", json={}, headers=quinn()).status_code == 200
    assert api.post("/api/v2/bots/closer/onboarded", json={}, headers=quinn()).status_code == 409
