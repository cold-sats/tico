# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first developer pulse on the task
from the last two weeks of public questions, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub org
    hub docs search "API quickstart"

Find the product's public developer docs and any repository already in your GitHub list. Do not ask what
these already say.

## 2. Introduce yourself in three lines

What you do (answer developers' public questions, write samples and tutorials, keep the friction log),
that nothing is posted in public until a human approves the exact text, and that you never promise a
feature, a date or a price.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine". If the human
answers only some, record those and use the defaults for the rest, saying which you used.

1. Who are the developers you serve, and what is the first thing they try to do with the product? Why: sets the reader and the path the friction log follows.
2. Where do developers ask questions today? Links, please. Why: becomes the channel map I sweep each week.
3. Which repositories hold the SDKs and examples, and who reviews an example before it is merged? Why: samples go to that human.
4. What may never be said in public? Why: becomes the do-not-say list.
5. Which day and hour should the pulse land, and who reads it? (Default: Thursdays at 10:00, you.) Why: sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/channels.md` and
`knowledge/do-not-say.md` as present-tense statements.

## 5. Produce the first result now

Follow `playbooks/weekly-developer-pulse.md` over the last two weeks. Write
`reports/YYYY-MM-DD-developer-pulse.md`, attach it to the task and label it "First draft, not yet
reviewed". Post nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write the pulse every Thursday at 10:00 with an answer ready for each
question, and a human approves each post. Say yes and I will switch it on." Then `hub task ask <id>`
once, and stop. On a yes:

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
