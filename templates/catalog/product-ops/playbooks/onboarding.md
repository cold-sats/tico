# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is five recorded answers and a first request ledger and review on the task, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task list --status open --status doing --status done
    hub meetings search "feature request"
    hub org

Read the Customer Insights Analyst's latest report if the team has one, and check whether the CRM and
GitHub are readable. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (a feature request ledger, the beta roster, the release calendar, roadmap hygiene), that you never promise a customer anything or change the roadmap, and that every customer message needs a human's yes.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine". If the human
answers only some, record those and use the defaults for the rest, saying which you used.

1. Where do feature requests arrive, and where are they kept today? The first ledger merges what exists.
2. Which betas are running, and who is in them? Seeds the beta roster.
3. Who owns the roadmap and each release, and where do dates live? Flags go to a named owner.
4. When a request ships, who tells the customers who asked? I prepare the list; a human sends it.
5. When should the weekly review land? (Default: Wednesdays at 09:00, the Head of Product.) Sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Start `knowledge/requests.md`, `knowledge/betas.md` and `knowledge/release-calendar.md` from what you can read.

## 5. Produce the first result now

Follow `playbooks/weekly-product-ops-review.md` on the real requests. Attach the review to the task, labelled "First draft, not yet reviewed". Send nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this review every Wednesday at 09:00. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
