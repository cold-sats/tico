# Org chart: people, teams, and the bots they use

Who is on which team, which group of bots that team owns, and who the primary user of each bot is.

The source is `registry/people.yaml` for the humans and
`registry/employees.yaml` for the bots. This page explains them; it
does not duplicate them. The hub renders the same mixed tree in the **Org** sidebar, so the page
in the app and this document always agree. Edit the YAML, not a list in prose. Bots read the
same chart through `hub org` / the `hub_org` MCP tool.

## The people

The example company, Acme, has Ana Rivera at the root. Department labels in the Org tree
(`org_groups` in `registry/people.yaml`) sit above each cluster of people: for example
**Marketing**, **Product**, **Engineering**, **Sales** and **Operations**. A department can have a
lead or no single lead.

Each person has a manager (`reports_to`), a team, and optionally a personal inbox bot. In the web
org chart, personal inbox bots appear as messaging icons beside their people; the icons open the
matching bot under **Message bots**. Shared mailboxes such as `shared@acme.example` can stay on the
roster for mail routing with `hidden: true`, so they do not appear in the tree.

Every Acme address is `<firstname>@acme.example`. Personal inbox bots come from the `inbox`
catalog template and read that person plus their reports (`org_read`). Each mailbox has its
own rules in `registry/mail-rules.yaml`. Photos prefer a Google Workspace Directory thumbnail
when domain-wide delegation includes `admin.directory.user.readonly`; otherwise the Slack
profile image stored on the roster.

## Bot groups

A team owns a group of bots: every bot whose `reports_to` chain in `registry/employees.yaml`
reaches that team's root bot, the root included. The roots are in the `teams` block of
`registry/people.yaml`. For example:

| Team | Root bot | The group |
|---|---|---|
| marketing | `cmo` | The CMO bot and everything under it: SEO, analytics, listening and content bots. |
| product | `product-manager` | The Product Manager bot and everything under it. |
| sales | `sales-ops` | Sales operations and the sales-process bots. |
| engineering | `cto` | The CTO bot, which monitors CI, deploys, alerts, security and cost. |

Bots that report to nobody and sit outside the teams belong to no team. Their primary user is
`default_user`.

An operations bot such as a **COO** can span every team. It reports to nobody and owns no team,
because its job is to serve all of them: it reads every bot's runs, tracks what each is still
missing, ages the needs-human queue, and publishes a weekly status broken out by department.
Routing a note, and writing the notes when a meeting is handed over, are **functions the hub
performs itself**, in seconds, with no run behind either.

## Who is the primary user of a bot

The person to ask when that bot needs a human, and the person its work is for.

1. Every person whose `primary_for` names the bot's **team** or the bot's own **slug** is a primary
   user of it. More than one person on a bot is fine.
2. If nobody claims it that way, the primary user is `default_user` (the root person).

So in Acme, Ana can be primary for the marketing group, Ben Okafor for the product group, and Ana
for everything outside the teams. Cara Mendes can also claim engineering so she can talk to the
CTO bot. To hand one specific
bot to someone without giving them the whole group, put that bot's slug in their `primary_for`.

## Where notes go

A person's `bot` is where the hub sends the notes and meetings they Send in **Auto** mode. Routing is a COO function the hub performs itself, with no run behind it: it matches the verified `Sender:` email against this roster first, then falls
back to one cheap model call over the active bots, then to the person's team root, then to the
COO (BotOps in a company whose assistant is off; see [onboarding](onboarding.md#the-assistant-botops-and-the-librarian-are-built-in)).

`bot: null` does not mean nobody. It means route by what the note actually says — the right default
for the root person, who talks to every bot, and for anyone whose team is not set yet. See
[`docs/meetings.md`](meetings.md) for how a meeting becomes a task,
the routing rules in your operations bot's knowledge, and `dispatcher/route.py` for the code.

## Adding a person

1. Add them to `registry/people.yaml` with an `id`, `name`, `email`, `title`, `team`, `primary_for`,
   `bot`, and `reports_to`. Set `hidden: true` to keep them off the org tree.
2. Add their email to `registry/hub-access.yaml` if they need to sign in to the hub. The two files
   are separate on purpose: this one says who a person is, that one says who may sign in.
3. A hub deploy reloads the roster from that file.
