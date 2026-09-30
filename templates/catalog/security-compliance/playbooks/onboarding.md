# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 30 minutes. The outcome is five recorded answers, a controls register with an owner
and a cadence on every control, a first monthly page, and a routine proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "security policy"
    hub docs search "SOC 2"
    hub org

Find the last audit report or readiness assessment, the policies and any evidence folder. What they
already say is not asked again.

## 2. Introduce yourself in three lines

What you do (the controls calendar, evidence collected before it is due, quarterly access reviews),
that you never change a setting, and that nothing reaches an auditor or customer without approval.

## 3. Ask, in one message

Numbered, each with its one-line why and a default.

1. Which framework and audit, and when is the next audit or observation window? Sets scope and dates.
2. Where are the controls, their owners and the evidence today? Seeds the register.
3. Which tools are in scope for access reviews, and who owns each? Each review goes to the owner.
4. Which policies must everyone accept, on joining or yearly? Becomes the acknowledgement tracker.
5. Who receives the monthly page, and when? (Default: the Operations Manager, the first of the month at 10:00.)

## 4. Record

Answers to `state.md` under `## Answers`, dated. Build `knowledge/controls.md` from the list you were
given; a control with no owner or cadence is kept and marked, never filled in by you. Start
`knowledge/evidence-log.md` from what is already in the evidence folder, dated by the file.

## 5. Produce the first result now

Follow `playbooks/monthly-controls-page.md` for the current month. Attach it labelled "First draft,
not yet reviewed". Request nothing from owners yet: the first page shows who would be asked for what.

## 6. Propose the routine and wait

Say: "If this is useful, I will run this page on the first of every month and send each owner their
evidence request once you approve the list. Say yes and I will switch it on." Then `hub task ask <id>`
once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md`, including the approved list of owners who may get evidence
requests, and set `state.md` to `Setup: finished`. On a no or a change, adjust `knowledge/` and
leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
