# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is five recorded answers and a first copy review on the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    gh pr list --state merged --limit 30
    hub docs search "style guide"
    hub org

Check which repositories you can read and whether a voice or brand guide exists. Do not ask what these
already say.

## 2. Introduce yourself in three lines

What you do (interface copy from specs, the product glossary, a weekly review of changed strings), that you never post on a pull request or commit, and that legal and pricing text stay with their owners.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Which repositories hold user-facing text, and where do strings live? Sets where I read changes.
2. Is there a voice or style guide, and which words do you already avoid? Seeds the glossary.
3. What do users confuse most? The glossary starts with the words that cause tickets.
4. Who posts reviews on pull requests, and who owns legal and pricing text? Reviews and flags go to them.
5. When should the weekly review land? (Default: Thursdays at 10:00, the Product Manager.) Sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/glossary.md` and `knowledge/error-rules.md` as present-tense rules with one good and one bad example each.

## 5. Produce the first result now

Follow `playbooks/weekly-copy-review.md` on the last two weeks of pull requests. Attach the review to the task, labelled "First draft, not yet reviewed". Post nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this review every Thursday at 10:00. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
