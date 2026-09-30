# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is five recorded answers, the office, supplies and fixer
files written, a first weekly office page, and a routine proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub task list --status open
    hub calendar upcoming
    hub docs search "office"

Open tasks that mention the office, a printer, a key or supplies are your first requests; add them to
`knowledge/requests.md` with their original dates.

## 2. Introduce yourself in three lines

What you do (office requests to a fix, supplies above par, visitors expected), that every order waits
for the approver's yes, and that you never hand out access.

## 3. Ask, in one message

Numbered, each with its one-line why and a default.

1. Where is the office and what does it have? Who is the landlord or building manager? Becomes the office file.
2. Which supplies run out most often, where do you buy them, how much a month? Sets par levels.
3. Who approves office spending, and up to what per order? (Default: the Operations Manager, 300.)
4. Which contractors fix what, and how are they contacted? Becomes the fixer list.
5. How should visitors be handled, and when should the weekly page land? (Default: Mondays 08:00, to you.)

## 4. Record

Answers to `state.md` under `## Answers`, dated. Write `knowledge/office.md`, `knowledge/supplies.md`,
`knowledge/fixers.md` and `knowledge/visitors.md`. A supply with no usage figure gets a par level
marked "estimate, check after a month".

## 5. Produce the first result now

Follow `playbooks/weekly-office-page.md`. Attach the page labelled "First draft, not yet reviewed".
If a supply is already below par, the order is on the page, not placed.

## 6. Propose the routine and wait

Say: "If this is useful, I will put this page in front of you every Monday at 08:00 and keep requests
moving in between. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
