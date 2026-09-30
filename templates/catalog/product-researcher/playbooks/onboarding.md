# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 30 minutes. The outcome is six recorded answers, a snapshot of the first one or two conversations you can read, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub meetings search --since YYYY-MM-DD
    hub docs search "interview"

Check what you can already reach: imported calls, research notes in the company docs, and the market graph (`hub market show`).
Do not ask what these already say. If there is nothing to read, that is answer two, and the first result is a plan for what to collect.

## 2. Introduce yourself in three lines

What you do (turn interviews, calls and feedback into snapshots, opportunities and research briefs), that you never contact a user or decide the roadmap, and that you say how many sources support each finding.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What outcome is the product team working toward this quarter, in one sentence? Why: Research is grouped under an outcome. Without one, I collect stories that answer nothing.
2. Where do interviews and user conversations live: meeting recordings, a folder of notes, survey exports? Can I read them? Why: Sets the sources. I say what I could not read instead of guessing.
3. Who are the users you most need to understand, and which decision is open right now? Why: The first brief is written for that decision, for that person.
4. Which competitors matter, and which of their features do people compare you to? Why: Sets the first comparison. Competitor facts go to the market graph, not to a file here.
5. What may I never store or quote: names, companies, anything from a private meeting? Why: Quotes are anonymised until you say otherwise.
6. When should the weekly research digest land, and who gets it? (Default: Thursdays at 10:00, to you.) Why: Sets the recipient and the first routine's schedule.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write the outcome and the open decision at the top of `knowledge/opportunities.md` and the never-quote rules into `knowledge/privacy.md`.

## 5. Do the first piece of work now

Take the first one or two conversations you can read and follow `playbooks/write-an-interview-snapshot.md`. Write the digest in the shape of `knowledge/examples/research-digest.md` to `reports/`, attach it to the task, labelled "First draft, not yet reviewed". Contact no one.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you a research digest every Thursday at 10:00 with new snapshots and the opportunities they support, and I will contact no one. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
