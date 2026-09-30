# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is five recorded answers, a first review on the task from a
real export, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub goals --all

Check whether an export is attached and whether any ads access is in your `employee.yaml`. Note any
marketing goal that names leads, trials or sales: it tells you which conversion matters. Do not ask
what these already say.

## 2. Introduce yourself in three lines

What you do (a weekly review of every paid campaign and three changes prepared for approval), that you
never touch an ad account or spend money, and that a person approves and applies each change.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Which ad platforms do you run, roughly what do you spend a month on each, and who can change the accounts today?
2. What is each campaign for, and what may one result cost? (Default: last 90 days' average.)
3. Where is a conversion tracked, and which conversions count?
4. How should the weekly exports reach me? (Default: a campaign report and a search-terms report for the last 7 days, attached to the task.)
5. What must never change without you: brand terms, a campaign, a daily budget ceiling?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/targets.md`: one block per
campaign (purpose, conversion, target cost per result, ceiling, owner), then the never-change rules.

## 5. Produce the first result now

Follow `playbooks/weekly-paid-media-review.md` on the attached export. Write
`reports/YYYY-MM-DD-paid-media.md`, attach it to the task and label it "First draft, not yet
reviewed". Change nothing and request no approval yet.

## 6. Propose the routine and wait

Say: "If this is useful, I will review every campaign each Monday at 09:00 from the exports you
attach. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
