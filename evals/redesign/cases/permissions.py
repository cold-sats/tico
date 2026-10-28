"""Permissions and audit (PLAN §7, scenarios 32-35): who may edit automations, caps and spend, what a bot may propose, and
what every change records. The same rules apply in the UI, the CLI and MCP; these checks use the API."""
import re

from ..harness import (CHRIS, CHRIS_REF, CLAUDE, CLAUDE_REF, LEAD, LEAD_ID, LEAD_REF, OPENAI_ID, OPENAI_REF, RELEASE_ID,
                       RELEASE_REF, W2, W3, Check, Scenario, Unmet, automation, body, edit_auto, find, get_caps, got,
                       make_group, put_cap, put_limit, replied, setup, untestable)


# ---------------------------------------------------------------------------------------------- helpers
def proposed(f, key):
    """A bot's cap change came back as a proposal (status pending), not applied."""
    reply = got(f, key)
    hit = find(reply.body, lambda d: d.get("status") == "pending") if 200 <= reply.status < 300 else None
    return hit is not None, f"{reply.status} {reply.excerpt()}"


def cap_still(f, key, sender, receiver, per_day):
    """The cap row for sender -> receiver in the listing `key` has this per_day."""
    setup(f, key)
    hit = find(body(f, key), lambda d: d.get("sender") == sender and d.get("receiver") == receiver)
    return bool(hit) and hit.get("per_day") == per_day, f"row {hit}"


def audit_rows(org):
    """The audit trail as Chris reads it (CONTRACT §5: `GET /api/v2/audit`)."""
    reply = org.api("get", "/api/v2/audit", wave=W3)
    if reply.status != 200:
        raise Unmet(W3, f"audit read: {reply.status} {reply.excerpt()}")
    return reply.body["rows"]


def audited(f):
    """Four writes (two cap saves, an automation saved and edited) each left an audit row, with an actor, and the
    5 to 7 cap change shows its before and after."""
    audit = got(f, "audit")
    change = [r for r in audit if re.search(r'per_day[\'"]?:\s*5\b', str(r["before"]))
              and re.search(r'per_day[\'"]?:\s*7\b', str(r["after"]))]
    ok = len(audit) >= 4 and all(r["actor"] for r in audit) and bool(change)
    return ok, f"{len(audit)} audit row(s); the 5 to 7 cap change {'found' if change else 'missing'}"


# ---------------------------------------------------------------------------------------------- 32 group lead
def s32_steps(org, f):
    org.step(f, "eng", make_group, org, "Engineering", bots=[LEAD_ID, OPENAI_ID], lead=LEAD_REF)
    org.step(f, "release", make_group, org, "Release", bots=[RELEASE_ID], lead=RELEASE_REF)
    org.step(f, "own_auto", lambda: automation(org, "Inbox · builder-openai", OPENAI_REF,
                                               group=f"group:{got(f, 'eng')}"))
    org.step(f, "other_auto", lambda: automation(org, "Release notes", RELEASE_REF,
                                                 group=f"group:{got(f, 'release')}"))
    org.step(f, "new_ok", lambda: automation(org, "Lead's inbox", OPENAI_REF, group=f"group:{got(f, 'eng')}", who=LEAD))
    org.step(f, "new_out", lambda: automation(org, "Lead's release", RELEASE_REF,
                                              group=f"group:{got(f, 'release')}", who=LEAD))
    org.step(f, "edit_ok", lambda: edit_auto(org, f, "own_auto", LEAD, enabled=False))
    org.step(f, "edit_out", lambda: edit_auto(org, f, "other_auto", LEAD, enabled=False))
    org.step(f, "cap_ok", put_cap, org, OPENAI_REF, LEAD_REF, 3, who=LEAD)
    org.step(f, "cap_out", put_cap, org, RELEASE_REF, CHRIS_REF, 3, who=LEAD)
    org.step(f, "limit_ok", put_limit, org, OPENAI_ID, {"hourly_usd": 4.0}, who=LEAD)
    org.step(f, "limit_out", put_limit, org, RELEASE_ID, {"hourly_usd": 4.0}, who=LEAD)


# ---------------------------------------------------------------------------------------------- 33 bot's own and reports
def s33_steps(org, f):
    org.step(f, "own", automation, org, "Own · builder-claude", CLAUDE_REF, who=CLAUDE)
    org.step(f, "report", automation, org, "Report · builder-claude", CLAUDE_REF)
    org.step(f, "peer", automation, org, "Peer · builder-openai", OPENAI_REF)
    org.step(f, "own_edit", lambda: edit_auto(org, f, "own", CLAUDE, enabled=False))
    org.step(f, "lead_edit", lambda: edit_auto(org, f, "report", LEAD, enabled=False))
    org.step(f, "peer_edit", lambda: edit_auto(org, f, "peer", CLAUDE, enabled=False))
    org.step(f, "peer_make", automation, org, "Sneaky · builder-openai", OPENAI_REF, who=CLAUDE)


# ---------------------------------------------------------------------------------------------- 34 bot proposes a cap
def s34_steps(org, f):
    org.step(f, "cap", put_cap, org, CLAUDE_REF, LEAD_REF, 5)
    org.step(f, "propose", put_cap, org, CLAUDE_REF, LEAD_REF, 2, who=CLAUDE)
    org.step(f, "caps", get_caps, org)


# ---------------------------------------------------------------------------------------------- 35 audit
def s35_steps(org, f):
    org.step(f, "cap_1", put_cap, org, CLAUDE_REF, LEAD_REF, 5)
    org.step(f, "cap_2", put_cap, org, CLAUDE_REF, LEAD_REF, 7)
    org.step(f, "auto", automation, org, "Audit · builder-claude", CLAUDE_REF)
    org.step(f, "auto_edit", lambda: edit_auto(org, f, "auto", CHRIS, enabled=False))
    org.step(f, "audit", audit_rows, org)


SCENARIOS = [
    Scenario(32, "perm-group-lead", "Group lead edits automations, caps and spend in the group; outside it, refused", s32_steps, [
        Check("lead creates an automation in her group", W3, lambda f: replied(f, "new_ok", 200, 201)),
        Check("lead edits an automation in her group", W3, lambda f: replied(f, "edit_ok", 200)),
        Check("lead refused on an automation outside her group", W3,
              lambda f: replied(f, "edit_out", 403, needs=("edit_ok",))),
        Check("lead refused to create an automation outside her group", W3,
              lambda f: replied(f, "new_out", 403, needs=("new_ok",))),
        Check("lead sets a cap for a teammate in her group", W2, lambda f: replied(f, "cap_ok", 200, 201)),
        Check("lead refused a cap outside her group", W2,
              lambda f: replied(f, "cap_out", 403, needs=("cap_ok",))),
        Check("lead sets a spend limit for a teammate in her group", W2, lambda f: replied(f, "limit_ok", 200)),
        Check("lead refused a spend limit outside her group", W2,
              lambda f: replied(f, "limit_out", 403, needs=("limit_ok",))),
    ]),
    Scenario(33, "perm-bot-reports", "Bot edits its own and its reports' automations; a peer's is refused", s33_steps, [
        Check("a bot makes an automation for itself", W3, lambda f: replied(f, "own", 200, 201)),
        Check("a bot edits its own automation", W3, lambda f: replied(f, "own_edit", 200, needs=("own",))),
        Check("a manager edits a report's automation", W3, lambda f: replied(f, "lead_edit", 200, needs=("report",))),
        Check("a bot edits a peer's automation: refused", W3,
              lambda f: replied(f, "peer_edit", 403, needs=("own_edit", "peer"))),
        Check("a bot makes an automation for a peer: refused", W3,
              lambda f: replied(f, "peer_make", 403, needs=("own",))),
    ]),
    Scenario(34, "perm-bot-proposes-cap", "Bot proposes a cap change: pending; Chris approves; BotOps applies", s34_steps, [
        Check("a bot's cap change comes back as a pending proposal", W2, lambda f: proposed(f, "propose")),
        Check("until a person approves, the cap stays at 5", W2, lambda f: cap_still(f, "caps", CLAUDE_REF, LEAD_REF, 5)),
        Check("Chris approves and BotOps applies the change", W2,
              untestable("CONTRACT names no approve route for cap proposals")),
    ]),
    Scenario(35, "perm-audit", "Every change writes actor, before and after", s35_steps, [
        Check("cap saves and automation writes each leave an audit row with an actor, the 5 to 7 change shown", W3, audited),
        Check("audit rows can be read back", W3,
              lambda f: (any(str(r.get("object", "")).startswith("automation:") for r in got(f, "audit")),
                         f"{len(got(f, 'audit'))} row(s)")),
    ]),
]
