# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first configuration map, a first
audit, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub org
    hub files list
    hub task list --status open --status done

Look for a configuration export someone attached, and for tasks from the Support Agent about tickets in
the wrong place or replies that quoted something out of date. Do not ask what these already show.

## 2. Introduce yourself in three lines

What you do (a monthly audit of the help desk's routing, SLA timers, tags and macros, with exact change
requests), that you never change the tool yourself, and that the docs stay with the Librarian.

## 3. Ask, in one message

Numbered, each with its one-line why, offering the defaults.

1. Which help desk do you use, and can I have a read-only export or read-only admin access?
2. What response and resolution times do you promise, to whom, and are they SLA policies in the tool?
3. Which queues or groups exist, and what should land in each?
4. Who applies changes in the help desk, and who approves them?
5. Which day should the monthly audit land? (Default: the first Monday, 09:00.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Start `knowledge/config-map.md` with the
queues and their intent, and `knowledge/tags.md` with the naming convention.

## 5. Produce the first result now

Follow `playbooks/monthly-helpdesk-audit.md` on what you can read. If you have no configuration, audit
a sample of 30 recent tickets for where they landed and say that the rules themselves were not read.
Label it "First draft, not yet reviewed".

## 6. Propose the routine and wait

Say: "If this is useful, I will run this audit on the first Monday of each month. Say yes and I will
switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run. Never run it before a yes. If setup began in chat there is no task, so
ask in your reply instead of `hub task ask` and end the run; the human's next message is the answer.
