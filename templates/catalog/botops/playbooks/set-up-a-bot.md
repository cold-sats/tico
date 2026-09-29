# Set up a bot

Triggered by a task that asks for a new bot. One bot per task, no schedule. Budget 30 minutes.

The outcome is a repository in {{company_name}}'s workspace that passes its readiness check, holds
instructions the owner recognises as what they asked for, and a task note that tells them the one
thing to read before they activate it. You never activate it yourself.

---

## 1. Read the task

The task names the bot slug, the template it comes from, and the display name, and it carries the
owner's reviewed instructions and the onboarding answers.

    hub task show <id>

A task titled `Build a bot: <name>` (from Getting started) carries a slug and a plain-language job
instead of a template. Pick the closest template in the catalog, and write `AGENT.md` for that job.

If any of those is missing, ask once with `hub task ask <id>` and stop until it is answered. Do not
invent a slug: it is the repository name, the value of `name:` in `employee.yaml`, and the label on
every task the bot ever gets, so renaming it later is real work.

## 2. Create the repository

    hub bot create <slug> --template <template> --name "<Display>"

That materialises `$HUB_WORKSPACE/emp-<slug>` from the catalog template, fills the company's names
into the placeholders, writes `knowledge/company.md` from the onboarding answers, and seeds the
template's `schedules:` into the hub as the bot's first routines (the result lists their ids).
Read what it produced before you change anything: the template is a starting point, not the
answer. From here on a routine is changed with `hub routine set`, not by editing the file.

## 3. Put the real instructions in

If the task carries the owner's reviewed instructions, replace `AGENT.md` with them. Keep the
section order the template uses, so `## Role`, `## Owns` and `## Never without approval` are still
where a reader and the readiness check expect them, and keep at least one real bullet under
`## Owns`.

If the task carries no reviewed instructions, tailor the template's `AGENT.md` to the onboarding
answers instead. Three things have to be true and specific in it:

- what the company does, in the words the answers used;
- what arrives where, so the bot knows which queue, inbox or source is its input;
- what never happens without a person, named concretely rather than as a general caution.

Cut every line that is not true for this company. A vague line left in is worse than a missing one,
because the bot will act on it. Do the same pass over `employee.yaml`: the display name, the labels,
and a schedule only if the owner asked for one.

If the instructions include a `Mailbox: <email>` line (inbox bots), replace every `{{mailbox}}` in
`employee.yaml` with that address. That is the mailbox this bot is assigned; do not invent one.

## 4. Check it

    hub bot check <slug>

Fix everything it reports as a failure: a missing `state.md`, an `AGENT.md` still identical to the
template, an empty `## Owns`, a `name:` that is not the slug, a schedule that would be refused. A
warning can stand if you say in the note what it is and why it is acceptable now. A credential that
does not resolve is not yours to create: name the variable on the task and say who supplies it.

## 5. Commit

Commit the new repository with a one line message that says what it is, for example
`Set up <slug> from the <template> template`. Nothing in the commit may contain a credential value.

## 5b. Give it a GitHub repository, if GitHub is connected

Skip this when the company has not connected GitHub; the bot stays on its computer. Otherwise the
repository you just committed exists only locally, so create an empty private one:

    hub github create-bot-repo <slug> --empty

Do not push it yourself. Your turn's token is for your own repository only, so a push of another
bot's history fails. Instead the bot's repository link (Settings, Bots) has to be `<org>/emp-<slug>`
(a bare `emp-<slug>` also resolves to the connected organization). The owner sets it there until
you can; say so in the task note. On the bot's next turn its runner sets `origin` to that
repository and publishes the history with the bot's own token, and never forces: if the repository
already holds different history it stops and Health says so. You do not push other bots'
repositories. If the command says the app was not given permission to create repositories, do not
work around it: say so in the note and leave it local. Never create a repository for a slug the
task did not name.

## 6. Finish the task

    hub task update <id> --status done --note "..."

The note says, in this order:

1. the repository path;
2. what you changed from the template, in a sentence or two;
3. the readiness result, with anything still warning;
4. the one thing the owner should read before activating, usually the `## Never without approval`
   section or a gap the answers did not fill.

The requester closes the task. The bot stays `planned` until the owner activates it.

## When it goes sideways

- **The slug already exists.** Stop. Do not overwrite a repository. Say so on the task and ask
  whether this is a rename, a second bot, or a mistake.
- **The template does not fit the job the answers describe.** Set it up from the closest template
  anyway, say plainly in the note which parts of the instructions you had to write from nothing, and
  suggest what a better template would contain.
- **The check fails on something outside the repository**, such as a runtime that is not installed
  or a profile with no sign in. That is the operator's to fix. Record the exact failing line on the
  task and finish; do not work around it.
