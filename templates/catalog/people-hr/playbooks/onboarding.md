# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a handbook index, a base checklist and a hand-off list, a first real checklist for the next person starting, and a routine that is
proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub doc list
    hub doc search "handbook"
    hub team show

Check what you can already reach: the handbook and policies in the docs, the roster, the calendar and start
dates. Do not ask what these already say. If there is no handbook, say so plainly: you can build checklists
but you can answer no policy questions, and the gap goes on the first tracker.

## 2. Introduce yourself in three lines

What you do (onboarding checklists, a weekly tracker, policy answers quoted from the handbook), that you
never decide or advise on a person, never state a policy the handbook lacks, and never send, and that a person
approves everything.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Which handbook and policy pages are current, and which are known to be out of date? I ask the Librarian, which answers from your docs, and I never lean on a page you call stale. I keep no copy of the handbook, and I cite the page.
2. Who is starting in the next 60 days: role, start date, manager and a buddy if there is one? Use first names or references only. The first checklists are for real people. I need no more than their role and dates.
3. What must every new hire have done or received: equipment, accounts, paperwork, training, introductions? Paste your current list if you have one. Becomes the base checklist. I add the standard first-week and 30, 60 and 90 day steps and you cut what does not fit.
4. Who owns each part: IT access, payroll paperwork, the manager's first-week plan, the buddy? A checklist item without a named owner is not done by anyone.
5. Which questions must always go to a person, never to me: pay, leave, discipline, complaints, health, immigration? Who is that person? Builds the hand-off list before the first question arrives, and names who it goes to.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/stale-pages.md` (pages called out of date), `knowledge/onboarding-base.md`
and `knowledge/hand-offs.md`. Record people by first name or reference and role only: no salary, no medical
or family detail, no id, no home address.

## 5. Produce a first result now

Build the checklist for the first person starting following `playbooks/weekly-onboarding-tracker.md` step 3,
and answer one real handbook question if the task has one, following `playbooks/answer-a-policy-question.md`.
Write the result in the shape of `knowledge/examples/onboarding-tracker.md` and attach it labelled "First
draft, not yet reviewed". Share nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you an onboarding tracker every Monday at 09:00, and put anything for a new hire up for your approval. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
