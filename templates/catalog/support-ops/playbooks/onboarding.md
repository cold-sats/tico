# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first configuration map, a first
audit, and the first routine confirmed.

---

## 1. Read before you ask

    hub team show
    hub file list
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

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the human in one line what it does: "I will run this audit on the first Monday of each month." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot setup-done

It tells {{app_name}} your setup is done. That clears your "Needs setup" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
