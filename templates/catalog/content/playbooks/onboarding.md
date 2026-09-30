# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 30 minutes. The outcome is five recorded answers, one real draft on the task and a
routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Read what the team already published if a link is given, and any voice or style notes attached.
Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (a rolling content plan and finished drafts with short versions), that you never publish,
post, reply or change live copy, and that a human decides what goes out.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Who reads what you publish, and what should they do after reading it?
2. Where do you publish, how often, and who presses publish?
3. Can you paste or link two pieces you are proud of and one that missed?
4. What do customers keep asking, and which three topics could you talk about for an hour?
5. What must never appear in public?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/voice.md` (with the two
good examples), `knowledge/plan.md` (four weeks, seeded from answer four) and the never-say rules
as present-tense statements.

## 5. Draft now

Take the top idea and follow `playbooks/draft-a-post.md`. Attach the draft and its short versions to
the task, labelled "First draft, not yet reviewed", in the shape of
`knowledge/examples/content-plan.md`. Nothing is published.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you the next four weeks and one finished draft every Monday at
09:00, and a human publishes. Say yes and I will switch it on." Then `hub task ask <id>` once, and
stop. On a yes:

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
