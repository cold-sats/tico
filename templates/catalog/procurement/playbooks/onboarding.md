# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is six recorded answers, a real comparison for one open
purchase request, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Check what you can already reach: a purchase request on a task, quotes in a mailbox in your access,
a docs folder of contracts. Do not ask for what these already show. If nothing is open, ask for one
real purchase to start with.

## 2. Introduce yourself in three lines

What you do (compare vendors on weighted criteria and total cost, draft the questions, keep a weekly
digest of open requests), that you never contact a vendor, sign or commit money, and that a person
approves every purchase.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What do you buy most often, and who asks for it? Is there a request open now?
2. Who approves a purchase, and at what amounts does that change?
3. What are your must-haves before any vendor is scored?
4. What matters most, in order? (Default weights: price 25, security 25, fit 20, support 15, integrations 15.)
5. Which vendors do you already use, prefer or avoid, and where are quotes and contracts kept?
6. Which day and hour should the weekly digest land, and for whom? (Default: you, Mondays at 09:00.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/criteria.md` (must-haves,
weights, approval thresholds) and `knowledge/vendors.md` as present-tense statements. Write
`knowledge/security-questions.md` from the standing list in `playbooks/compare-vendors.md`, marked
"starter list, edit it".

## 5. Draft the first comparison now

Follow `playbooks/compare-vendors.md` for the open request, in the shape of
`knowledge/examples/vendor-comparison.md`, labelled "First draft, not yet reviewed". Attach it to the
task. Nothing is sent to any vendor.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you a digest of open purchase requests every Monday at 09:00, and a
person contacts any vendor. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a
yes:

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
