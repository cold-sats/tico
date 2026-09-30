---
service: aside
title: Aside (the company browser)
kind: browser
summary: Signed-in websites through the dedicated bot browser, Aside, with the sites and verbs a bot may use declared in its employee.yaml.
access: "`$HUB_DIR/connectors/browser.py` — nobody drives Chrome, the Orca browser or `aside` directly"
credentials:
  - none in a bot's environment — the owner signs in to each site once, in Aside; sessions and re-logins are Aside's business
  - ASIDE_CLI (optional) — path to the `aside` binary when it is not ~/.local/bin/aside
declared_as: |
  - service: aside
    identity: the company browser (Aside), the owner's sessions
    account: u0                       # optional Aside account
    sites: [app.example.com]               # hosts it may open; a subdomain of a listed host counts
    can: [read]                       # [read] looks; [read, act] clicks, types, submits, runs `task`
writes: approval
owner: owner
aliases: [browser]
---

## What it is

Aside (aside.com) is a Chromium browser with its own agent, password manager and CLI.
`aside repl` runs Playwright-style JavaScript in the signed-in browser; `aside exec` hands a
job to Aside's agent. The hub's connector, `connectors/browser.py`, is the only way a bot reaches
either: it checks the bot's `access:` entry, refuses hosts outside `sites:`, refuses actions
for a read-only bot, and appends every call to `<projects>/runtime/browser-audit.jsonl`. The
skill that teaches a model the REPL is `skills/aside-browser/SKILL.md`; run `aside guide repl`
before writing REPL code. The CLI installs with
`curl -fsSL https://releases.aside.com/install.sh | bash`.

## What data it has

Whatever the signed-in sites show. Typical declarations: the company's own app (read only, for
support-style bots); social sites and news (a listening bot, read); ad dashboards such as
`ads.google.com` (read); a design tool (act). Each is a `sites:` entry in the bot's own
`employee.yaml`.

**The owner's social sessions are the listening bot's alone**. The connector refuses
any other employee that names a social site (X, Reddit, LinkedIn, Facebook, Instagram, TikTok,
YouTube and the rest of `SOCIAL_HOSTS` in `connectors/browser.py`) in its `sites:` or its code;
ad-account dashboards on those domains are not social reading. The listening bot saves what it reads to the hub (`hub listening save`), the decision model routes
each post to the inboxes that want it (the company's `registry/listening.yaml`), and every other bot works its
inbox (`hub listening item list`, `hub listening item resolve`) or asks the listening bot by task for a lookup.

## How a bot uses it

```bash
$HUB_DIR/connectors/browser.py doctor
$HUB_DIR/connectors/browser.py tabs --as <slug>                                      # what is open on the bot's sites
$HUB_DIR/connectors/browser.py repl --as <slug> "const p = await openTab('https://app.example.com/queue'); ..."
$HUB_DIR/connectors/browser.py repl --as <slug> --file steps.js
$HUB_DIR/connectors/browser.py task --as <slug> "Find the pricing page on app.example.com and ..."   # Aside's own agent; needs act
```

Exit codes: `0` ok, `1` failure (CLI missing, Aside not running, timeout), `2` a hub policy
refused it. The REPL stops after 120 s; a `task` after 900 s (`ASIDE_TASK_TIMEOUT`).

## Rules

- The bot's `employee.yaml` must declare `service: aside` with `sites:`. Every URL literal in
  the code, and the text of a `task`, must stay on those hosts; anything else is refused before
  the browser is touched.
- `can: [read]` allows REPL reads only. The connector refuses `.click`, `.dblclick`, `.fill`,
  `.type`, `.press`, `.check`, `.uncheck`, `.selectOption`, `.setInputFiles`, `.dragTo`,
  `.hover`, `.tap`, `.evaluate`, `.evaluateHandle`, `.route`, `.goto`, `page.keyboard`,
  `page.mouse` and the `task` command. `can: [read, act]` allows them.
- `act` is not a licence to send or post: outbound sends, public posts and spend still follow
  `outbound_send`, `policies/approvals.md` and the read-only period in
  `policies/shared-rules.md`. That is the playbook's job to honour.
- Logins are never a bot's job. The owner signs in once in Aside; a login page, a captcha or a
  challenge means stop and say so.
- Never drive Chrome, the Orca browser or the `aside` CLI directly; the connector is the only
  audited path.

## Recipes

- Read a page: `openTab(url)` then read titles, text or a snapshot in the REPL; keep the code
  in a `--file` when it is more than a line so the audit shows what ran.
- Watch a dashboard read-only (ads, an email tool, your own app): open the tab, read the numbers, never
  Edit, Save, Apply, Enable, Pause or Create.
- Hand a research job to Aside's agent (act only): `task --as <slug> "..."` with the sites
  named in the prompt; the agent works inside the same host allow-list.

## Gotchas

- A subdomain of a listed host counts; a different host does not, even for a redirect.
- The read-only check is textual: a read-only bot cannot smuggle a click through a helper,
  and `.evaluate` counts as an action.
- A `1` from `doctor` usually means Aside is not running or the CLI is outdated
  (`aside --update`, then `aside guide` again).

## Learnings

What bots and people learn about this integration is added with `hub tool learn aside "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
