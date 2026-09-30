# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 30 minutes. The outcome is five recorded answers, first win/loss notes on the task from
real closed deals, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub org --team sales
    hub meetings search "pricing"

Check how many sales calls are imported and from when, whether a CRM is in your access, and which sales
roles already report (`hub updates --kind weekly`). Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (win/loss notes, talk tracks and objection answers, ramp plans), that you coach the work and
never grade a human, and that nothing reaches a buyer without a human's approval.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Who is on the sales team, who joined in the last six months, who starts next?
2. Which deals closed in the last 90 days, and where are their calls and notes?
3. Which objections come up most, and who handles each best?
4. Do you, or will you, talk to buyers after a decision? Who would?
5. What must a new seller know by day 30, 60 and 90? (Default: product and ICP by 30, running discovery by 60, a first deal by 90.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Seed `knowledge/objections.md` and
`knowledge/talk-tracks.md` with what the team named, marked "not yet confirmed by a call", write
`knowledge/interview-guide.md`, and one `knowledge/ramp/<seller>.md` per new seller.

## 5. Produce the first result now

Follow `playbooks/weekly-win-loss.md` over the last 90 days instead of one week. Write
`reports/YYYY-MM-DD-win-loss.md`, attach it and label it "First draft, not yet reviewed".

## 6. Propose the routine and wait

Say: "If this is useful, I will write win/loss notes every Friday at 10:00 from the week's closed deals.
Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
