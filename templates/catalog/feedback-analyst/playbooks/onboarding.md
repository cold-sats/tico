# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is five recorded answers, a real first report on the task, and
a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub task list --status done
    hub meetings search "customer" --since <two weeks ago>

Check what feedback you can already reach: Support Agent's digests, imported customer calls, a mailbox
or channel in your access, files attached to the task. Do not ask what these already say. If you cannot
read any feedback, that is answer one, and a task for the owner if they want a source connected.

## 2. Introduce yourself in three lines

What you do (a weekly report of feedback themes with counts and three suggested actions), that you never
contact a customer or decide what to build, and that a human approves everything that leaves.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Where does customer feedback arrive today, and which can you read?
2. Who reads the weekly report, who decides what to build or fix, and which day? (Default: you, Mondays at
   08:00.)
3. Which parts of the product or service matter most now, and what themes do you already track?
4. Which customers or segments should weigh more?
5. What is off limits: personal data, legal complaints, anything about a named employee?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/themes.md` (the human's
themes first, then what the data adds, each with a definition and an example), `knowledge/segments.md`
(weights and the exclusion list) and start `knowledge/trends.md`.

## 5. Report now

Follow `playbooks/weekly-feedback-report.md` on the last two weeks of feedback, in the shape of
`knowledge/examples/weekly-feedback-report.md`. Attach it to the task, labelled "First draft, not yet
reviewed". Send it to nobody else.

## 6. Propose the routine and wait

Say: "If this is useful, I will draft this report every Monday at 08:00 and send it only to you. Say yes
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
