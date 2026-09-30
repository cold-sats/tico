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


def slugs(rows):
    return [row["template"] for row in rows]


def chart_of(said, home="human:morgan"):
    return O.full_chart(CARDS, said, home)


def grouped(chart):
    return {row["team"]: [m["template"] for m in row["members"]] for row in chart["teams"]}


def test_the_starter_team_is_three_bots_and_a_fourth_when_software_is_the_product():
    """Chief of Staff, Support Agent and Sales Drafter, plus Issue Triage for a software company; tools and pains change nothing."""
    plain = O.choose(CARDS, answers(customers="businesses", software_product="no"))
    assert slugs(plain) == ["chief-of-staff", "support", "sales"]
    assert [row["slug"] for row in plain] == ["chief-of-staff", "support", "sales"]
    assert all(row["why"] and row["matched_pain"] == "" for row in plain)
    software = O.choose(CARDS, answers(customers="businesses", software_product="yes"))
    assert slugs(software) == ["chief-of-staff", "support", "sales", "issue-triage"]
    assert software[3]["why"].startswith("Software is your product. ")
    # Nothing else in the answers moves it: not the sale, the size, work arriving, nor an old record's pains or ticked tools.
    assert slugs(O.choose(CARDS, answers())) == slugs(plain)
    assert slugs(O.choose(CARDS, answers(customers="consumers", team_size="3", work_arrives=["email", "crm"]))) == slugs(plain)
    old = answers(pains=["leads go cold"], pains_text="email is out of control", tools=["mail", "github", "meetings"])
    assert slugs(O.choose(CARDS, old)) == slugs(plain)
    assert O.recommend(CARDS, answers(software_product="yes")) == slugs(software)


def test_a_description_may_add_one_obvious_starter_and_no_more():
    """Simple word matching on "What you do" against a card's pains and summary adds at most one card, predictably."""
    said = answers(what_we_do="An online shop: writing campaign emails takes days and we never send a newsletter.")
    team = O.choose(CARDS, said)
    assert slugs(team) == ["chief-of-staff", "support", "sales", "email-marketing"]
    assert team[3]["matched_pain"] == "writing campaign emails takes days"
    assert team[3]["why"].startswith("It fits what you do. ")
    assert O.choose(CARDS, said) == team                                          # the same answers give the same team
    assert len(O.choose(CARDS, {**said, "software_product": "yes"})) == 5 == O.STARTER_TEAM_MAX
    # A description that matches nothing, or nothing at all, adds nothing; nor does it add a lead, an Engineering card for a
    # company that has no software, or a card the company is not for.
    assert len(O.choose(CARDS, answers(what_we_do="We make candles."))) == 3
    assert len(O.choose(CARDS, answers(what_we_do=""))) == 3
    triage = answers(what_we_do="issues pile up untriaged and pull requests wait days for a first review")
    assert "issue-triage" not in slugs(O.choose(CARDS, triage)) and len(O.choose(CARDS, triage)) == 3
    assert {"engineering-lead", "pr-reviewer"} & set(slugs(O.choose(CARDS, {**triage, "software_product": "yes"}))) == {"pr-reviewer"}
    assert "sales-lead" not in slugs(O.choose(CARDS, answers(what_we_do="leads go cold and I can't tell which deals are really moving")))


def test_the_full_chart_is_every_starter_grouped_by_team_and_engineering_only_for_software():
    """Every starter template, each pack's lead in front; Engineering appears only when software is the product."""
    starters = {card["template"] for card in CARDS if card["starter"]}
    assert len(starters) >= 25 and not any(card["required"] for card in CARDS if card["template"] in starters)
    chart = chart_of(answers(customers="both", software_product="yes"))
    teams = grouped(chart)
    assert list(teams) == ["Leadership", "Sales", "Marketing", "Support", "Operations", "Engineering"]
    assert {slug for members in teams.values() for slug in members} == starters
    assert {"issue-triage", "engineering-lead", "pr-reviewer"} <= set(teams["Engineering"])
    assert chart["held_back"] == []
    leaders = {row["team"]: row["lead"] for row in chart["teams"]}
    assert leaders == {"Leadership": "chief-of-staff", "Sales": "sales-lead", "Marketing": "marketing-lead",
                       "Support": "support-lead", "Operations": "ops-manager", "Engineering": "engineering-lead"}
    assert all(row["members"][0]["slug"] == row["lead"] and row["members"][0]["lead"] for row in chart["teams"])
    assert not any(m["lead"] for row in chart["teams"] for m in row["members"][1:])
    reports = {m["slug"]: m["reports_to"] for row in chart["teams"] for m in row["members"]}
    assert reports["chief-of-staff"] == "human:morgan" and reports["inbox"] == "chief-of-staff"
    assert reports["sales"] == "sales-lead" and reports["sales-lead"] == "human:morgan"
    assert {r for r in reports.values() if r.startswith("human:")} == {"human:morgan"}      # every lead reports to the owner

    # No software: the same company without the whole Engineering team, and nothing else missing.
    without = grouped(chart_of(answers(customers="both", software_product="no")))
    assert "Engineering" not in without and without["Sales"] == teams["Sales"]
    assert {slug for members in without.values() for slug in members} == starters - set(teams["Engineering"])
    assert "Engineering" not in grouped(chart_of(answers()))                                  # and it is not the default
    # Nothing about pains, tools or size shrinks or grows the chart.
    assert grouped(chart_of(answers(customers="both", software_product="yes", pains=["leads go cold"], tools=["mail"], team_size="3"))) == teams


def test_a_consumer_only_company_skips_the_templates_written_for_business_customers():
    """A card whose `recommend_when` names sells_to_businesses but not sells_to_consumers is business-only."""
    business_only = {card["template"] for card in CARDS if card["starter"] and "sells_to_businesses" in card["recommend_when"]
                     and "sells_to_consumers" not in card["recommend_when"]}
    assert {"sales", "sales-lead", "ar-followup", "legal-review", "strategy-planning"} <= business_only
    consumers = grouped(chart_of(answers(customers="consumers", software_product="yes")))
    offered = {slug for members in consumers.values() for slug in members}
    assert not offered & business_only and "Sales" not in consumers
    assert {"support", "content", "email-marketing", "inbox"} <= offered
    # Businesses, both, and a company that did not say all keep them.
    for customers in ("businesses", "both", ""):
        kept = {slug for members in grouped(chart_of(answers(customers=customers, software_product="yes"))).values() for slug in members}
        assert business_only <= kept, customers
    # A team led by a business-only template is led by its first member when that template is skipped.
    assert all(row["lead"] == row["members"][0]["slug"] for row in chart_of(answers(customers="consumers"))["teams"])


def test_tools_gate_nothing_at_onboarding():
    """No template is held back or proposed differently for a tool: each bot asks for what it needs when it starts."""
    said = answers(customers="businesses", software_product="yes")
    ticked = {**said, "tools": ["mail", "chat", "crm", "github", "meetings", "docs"]}
    assert O.choose(CARDS, ticked) == O.choose(CARDS, said)
    assert chart_of(ticked) == chart_of(said)
    rows = [m for row in chart_of(said)["teams"] for m in row["members"]]
    assert any(row["prerequisites"] for row in rows)                                # still described, never a condition
    assert not any("met" in need for row in rows for need in row["prerequisites"])
    assert not hasattr(O, "pain_options") and not hasattr(O, "FEATURED_PAINS")


def test_the_onboarding_record_serves_the_two_starting_points_and_ignores_old_answers(environment):
    """GET and PUT keep their shape: `held_back` is empty, `pain_options` is gone, and pains and tools are kept but never read."""
    api = environment()
    real_starters(api, "chief-of-staff", "support", "sales", "issue-triage")
    who = signed_in()
    saved = api.put("/api/v2/onboarding", headers=who, json={"answers": {
        "what_we_do": "We sell software to studios", "customers": "businesses", "software_product": "yes",
        "pains": ["leads go cold"], "pains_text": "email is out of control", "tools": ["mail", "github"]}})
    assert saved.status_code == 200
    body = saved.json()
    assert body["recommended"] == ["chief-of-staff", "support", "sales", "issue-triage"] == slugs(body["recommendations"])
    assert body["held_back"] == [] and body["full_chart"]["held_back"] == [] and "pain_options" not in body
    assert body["answers"]["pains"] == ["leads go cold"] and body["answers"]["tools"] == ["mail", "github"]     # kept, not read
    assert api.get("/api/v2/onboarding", headers=who).json()["recommended"] == body["recommended"]


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
