# Team chart: humans, groups, and the bots they use

Who is in which group, which bots each group holds, and who each bot is mainly for. A group is part of the team, and a group can hold groups.

The source is `registry/people.yaml` for the humans and
`registry/employees.yaml` for the bots. This page explains them; it
does not duplicate them. Tico renders the same mixed tree in the **Team** sidebar, so the page
in the app and this document always agree. Edit the YAML, not a list in prose. Bots read the
same chart through `hub org` / the `hub_org` MCP tool (`GET /api/v2/org`): the humans, and every bot the caller may see (see
[permissions.md](permissions.md)) with its `reports_to`, its `department` and its `template`. A bot's `department`
is its group; a bot with none takes the group of its template in the team builder, then of the bot it reports to, so a
group head's reports carry the head's group. `hub people list` is the humans alone.

## The humans

The example team, Acme, has Ana Rivera at the root. Group labels in the team tree
(`org_groups` in `registry/people.yaml`) sit above each cluster of humans: for example
**Marketing**, **Product**, **Engineering**, **Sales** and **Operations**. A group can have a
lead or no single lead.

Each human has a manager (`reports_to`), a group (`team`), and optionally a personal message bot. In the web
team chart, personal message bots appear as messaging icons beside their humans; the icons open the
matching bot under **Message bots**. Shared mailboxes such as `shared@acme.example` can stay on the
roster for mail routing with `hidden: true`, so they do not appear in the tree.

Every Acme address is `<firstname>@acme.example`. Personal message bots come from the `inbox`
template and read that human plus their reports (`org_read`). Each mailbox has its
own rules in `registry/mail-rules.yaml`. Photos prefer a Google Workspace Directory thumbnail
when domain-wide delegation includes `admin.directory.user.readonly`; otherwise the Slack
profile image stored on the roster.

## Bot groups

A group holds bots: every bot whose `reports_to` chain in `registry/employees.yaml`
reaches that group's root bot, the root included. The roots are in the `teams` block of
`registry/people.yaml`. For example:

| Group | Root bot | The bots |
|---|---|---|
| marketing | `cmo` | The CMO bot and everything under it: SEO, analytics, listening and content bots. |
| product | `product-manager` | The Product Manager bot and everything under it. |
| sales | `sales-ops` | Sales operations and the sales-process bots. |
| engineering | `cto` | The CTO bot, which monitors CI, deploys, alerts, security and cost. |

Bots that report to nobody and sit outside the groups belong to no group. The human they are mainly for is
`default_user`.

An operations bot such as a **COO** can span every group. It reports to nobody and owns no group,
because its job is to serve all of them: it reads every bot's runs, tracks what each is still
missing, ages the queue of what needs a human, and publishes a weekly status broken out by group.
Routing a note, and writing the notes when a meeting is handed over, are **functions Tico
performs itself**, in seconds, with no run behind either.

## Who a bot is mainly for

The human to ask when that bot needs a human, and the human its work is for.

1. Every human whose `primary_for` names the bot's **group** or the bot's own **slug** is a primary
   human for it. More than one human on a bot is fine.
2. If nobody claims it that way, the primary human is `default_user` (the root human).

So in Acme, Ana can be primary for the marketing group, Ben Okafor for the product group, and Ana
for everything outside the groups. Cara Mendes can also claim engineering so she can talk to the
CTO bot. To hand one specific
bot to someone without giving them the whole group, put that bot's slug in their `primary_for`.

## Where notes go

A human's `bot` is where Tico sends the notes and meetings they Send in **Auto** mode. Routing is a COO function Tico performs itself, with no run behind it: it matches the verified `Sender:` email against this roster first, then falls
back to one cheap model call over the active bots, then to the human's group root, then to the
COO (BotOps in a team whose assistant is off; see [Finish setup](onboarding.md#the-assistant-botops-the-librarian-and-the-goal-manager-are-built-in)).

`bot: null` does not mean nobody. It means route by what the note actually says — the right default
for the root human, who talks to every bot, and for anyone whose group is not set yet. See
[`docs/meetings.md`](meetings.md) for how a meeting becomes a task,
the routing rules in your operations bot's knowledge, and `dispatcher/route.py` for the code.

## Adding a human

1. Add them to `registry/people.yaml` with an `id`, `name`, `email`, `title`, `team`, `primary_for`,
   `bot`, and `reports_to`. Set `hidden: true` to keep them off the team tree.
2. Add their email to `registry/hub-access.yaml` if they need to sign in to Tico. The two files
   are separate on purpose: this one says who a human is, that one says who may sign in.
3. A Tico deploy reloads the roster from that file.
