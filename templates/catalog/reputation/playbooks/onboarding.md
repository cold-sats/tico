# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 40 minutes. The outcome is five recorded answers, a first read of every surface on
the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub market show          # only if the team has a market page

Search for the team's listings under its name and old names. Do not ask what a search already
answers. Note which surfaces you cannot read; that is part of answer one.

## 2. Introduce yourself in three lines

What you do (read the review listings, keep the ledger, draft one batch of honest replies and
rule-based flags per surface), that you never write, buy or steer a review and never act on a
listing without an approved batch, and that a human carries out or enables each batch.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Which review sites matter to your buyers, and where are your listings?
2. Have you claimed each listing, and who holds the login?
3. What is your current rating on each, and which review worries you most?
4. Who approves a reply or a flag, and what tone? Can you paste one reply you liked?
5. Which customers should be invited to review on the software sites, and at what milestone?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Fill `knowledge/surfaces.md` with the
listings, and check each rule against the platform's current policy page, dated.

## 5. Read now

Follow `playbooks/weekly-review-sweep.md` steps 1 to 3 and 5 once: read each surface, fill the ledger, write
the digest in the shape of `knowledge/examples/review-sweep.md` and attach it to the task, labelled
"First draft, not yet reviewed". Draft the first batch per `playbooks/work-queue.md` steps 1 to 3 as a
list for review only; request no approval yet and act on nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will read your review listings every Monday at 09:00 and bring you one
batch per surface to approve. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
