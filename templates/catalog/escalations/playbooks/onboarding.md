# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 20 minutes. The outcome is five recorded answers, a register of open escalations,
a first daily digest, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub org
    hub task list --status open --status waiting
    hub updates --kind weekly --limit 4

Look for tasks that are escalations in all but name: a customer who has written three times, a ticket
older than a week from a large account, a bug waiting on engineering. Do not ask what these show.

## 2. Introduce yourself in three lines

What you do (drive each escalated ticket to resolution with one owner, a timeline, bug reports and
updates on cadence), that every customer update is approved by a human before it goes, and that you
never promise money or dates.

## 3. Ask, in one message

Numbered, each with its one-line why, offering the defaults.

1. What makes a ticket an escalation here? Name the triggers.
2. Which customers are VIP or have contractual support terms, and what do those promise?
3. How often should an escalated customer hear from us at each severity? (Default: sev 1 every 4
   business hours, sev 2 daily, sev 3 twice a week.)
4. Who can own an escalation, who approves customer updates, who in engineering takes a bug report?
5. Who gets the daily digest, and when? (Default: the head of support and you, weekdays 08:30.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated, and write `knowledge/escalation-rules.md`
with the triggers, severities (one example each), cadence, VIP list and owners.

## 5. Produce the first result now

Open a case file for each escalation you found (`playbooks/open-an-escalation.md`, without sending
anything), write `knowledge/register.md`, then follow `playbooks/daily-escalation-digest.md`. Label
the digest "First draft, not yet reviewed".

## 6. Propose the routine and wait

Say: "If this is useful, I will send this digest every weekday at 08:30. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run. Never run it before a yes. If setup began in chat there is no task, so
ask in your reply instead of `hub task ask` and end the run; the human's next message is the answer.
