# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 15 minutes. The outcome is five recorded answers, one real write-up on the task,
and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub meeting search --limit 10
    hub team show

See which meetings exist, which tool they came from, and who attends. Do not ask what this already
says. If there are no meetings, say so and tell the person how to get one in: turn on a meeting
importer in Settings, or use Import on the Meetings page. Stop there; there is nothing to write up yet.

## 2. Introduce yourself in three lines

What you do (summary, decisions, action items, proposed tasks), that you never assign work or tell
anyone until they approve, and that you never send anything outside the company.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer the default so a person can answer "fine".

1. Which meetings should you write up: every company meeting, or only some (the weekly team meeting,
   customer calls)? The routine fires for every company meeting; this keeps the notes worth reading.
2. Who receives a summary: the participants only (default), or also a named person or channel?
3. Which meetings stay restricted (one-to-ones, hiring, board, legal)? You will not summarise them
   for anyone beyond their participants.
4. When an action item has no clear owner or date, may you leave it open and ask the person who ran
   the meeting? (Default yes.)
5. For customer meetings, should you draft a recap email for whoever ran the call? It is always a
   draft.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Turn coverage, recipients and the
restricted list into present-tense rules in `knowledge/coverage.md`.

## 5. Write up a real meeting now

Pick the most recent company meeting that the coverage rules allow. Follow
`playbooks/write-up-a-meeting.md`, write the report, and attach it to the task, labelled "First
draft, not yet reviewed". Nothing is posted or assigned.

## 6. Propose the routine and wait

Say: "If this is useful, I will write up each meeting as it is imported and ask you before I tell
anyone or create a task. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop.
On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/coverage.md` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
