# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first weekly technical prep on the
task from real deals, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub doc search "security"
    hub doc search "API"
    hub meeting search "demo"

Check which product, API and security docs exist and how current they are, and which deals have a demo or
evaluation coming (`hub calendar list`). Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (technical discovery, demo scripts, POC plans, technical and security answers), that you never
promise what has not shipped, and that the deal owner approves everything a prospect sees.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What does a technical evaluation look like here, and which systems do buyers usually connect?
2. Where are the product, API and security docs, and who owns security and compliance answers?
3. Do you run proofs of concept or trials: how long, who sets them up, what decides them? (Default: two weeks, three to five criteria.)
4. One demo that worked and one that did not; what must a demo never show?
5. Which deals need technical work now, and who owns each?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/technical-discovery.md` (the
questions for every deal), `knowledge/never-show.md`, and a note per deal you were given.

## 5. Produce the first result now

Follow `playbooks/weekly-technical-prep.md`. Write `reports/YYYY-MM-DD-technical-prep.md`, attach it and
label it "First draft, not yet reviewed". Nothing goes to a prospect.

## 6. Propose the routine and wait

Say: "If this is useful, I will prepare every deal's technical steps each Wednesday at 09:00. Say yes
and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
