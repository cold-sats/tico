# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, one real investigation, a first tier
2 report, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub org
    hub task list --status open --status waiting
    hub docs search "API"

Find open tickets that look technical (error messages, integrations, data that looks wrong) and check
whether GitHub is in your access. Do not ask what these already show.

## 2. Introduce yourself in three lines

What you do (investigate the tickets frontline cannot solve, reproduce them, write bug reports and
workarounds), that a person approves every customer reply and files every bug, and that you never touch
a customer's account.

## 3. Ask, in one message

Numbered, each with its one-line why, offering the defaults.

1. Which products, APIs and integrations do customers ask technical questions about, and where are the docs?
2. Is there a sandbox account I may use, and which read-only logs or dashboards can I see?
3. Where do bugs go, who files them, and what must a report contain?
4. What makes a ticket tier 2? (Default: an error, an API or integration problem, wrong-looking data,
   anything the docs do not explain.)
5. Who approves technical replies, and who gets the weekly report? (Default: the head of support,
   Thursdays 09:00.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated, and start `knowledge/diagnosis.md` with the
sandbox, the log sources and the bug report format.

## 5. Produce the first result now

Run `playbooks/investigate-a-ticket.md` on the oldest open technical ticket, then follow
`playbooks/weekly-tier2-report.md`. Label the report "First draft, not yet reviewed".

## 6. Propose the routine and wait

Say: "If this is useful, I will write this report every Thursday at 09:00. Say yes and I will switch it
on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run. Never run it before a yes. If setup began in chat there is no task, so
ask in your reply instead of `hub task ask` and end the turn; the person's next message is the answer.
