# Propose a new people bot

Triggered from the weekly summary, or by a task, when recurring people work has no owner. Budget 15
minutes. The outcome is one specific proposal the owner can say yes or no to, and on a yes, one task
for BotOps. You never create a bot yourself.

---

## 1. Show the work is recurring

Count the unowned requests of one kind in the last 30 days (`hub task list`, the routing log) and name
three with dates. One-off work is not a reason to add a bot; route it to a human.

## 2. Pick the template

    hub catalog
    hub org

Choose one template from `team_templates` in this bot's card that owns exactly that work and is not
already in `hub org`. Read its card: its summary, its first routine and what it needs to start.

## 3. Propose

On the task, in five lines: the recurring work and how often; the evidence; the template and its name;
its first routine as the card states it; that it reports to you and starts parked until its own setup.
Ask once with `hub task ask <id>`: "Set up <name>?"

## 4. On the owner's yes

    hub task create --owner botops --title "Set up <template>" --body "<why, the evidence, its first routine, reports to people-lead>"

Record the decision in `memory/decisions.md` and add the bot to `knowledge/team.md` and
`knowledge/routing.md` once BotOps says it exists. On a no, record why, so the same proposal is not
made again next week.
