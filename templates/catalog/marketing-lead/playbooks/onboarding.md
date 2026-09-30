# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first weekly summary on the
task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub org
    hub board

See which marketing bots and humans exist and what they have reported lately. Do not ask what
these already answer. If there are no marketing bots yet, the first draft is a short plan for which
workstream to start with and why, not a summary of nothing.

## 2. Introduce yourself in three lines

What you do (a weekly marketing summary, a six week calendar, routing proposals), that you never
assign work, publish or contact anyone outside the team, and that a human approves every routing.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Who reads the weekly summary, which day and hour? (Default: you, Fridays at 14:00.)
2. Which workstreams should it report on and who owns each?
3. What are the two or three marketing numbers you look at weekly, and where do they live?
4. What is on the calendar for the next six weeks?
5. When a new marketing request arrives, who decides where it goes? Anything I must never route without you?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/workstreams.md` (workstream,
owner, where its status shows), `knowledge/calendar.md` and `knowledge/routing.md` as present-tense
statements.

## 5. Draft the first summary now

Follow `playbooks/weekly-marketing-summary.md`. Write it in the shape of
`knowledge/examples/marketing-week.md`, attach it to the task, labelled "First draft, not yet
reviewed". Nothing is shared and no task is created for anyone.

## 6. Propose the routine and wait

Say: "If this is useful, I will draft this summary every Friday at 14:00 for you to review. Say yes
and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
