# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first weekly account review on the
task from the real accounts, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub team show
    hub meeting search "renewal"

Check what you can already reach: a CRM entry in your access, contracts attached to tasks or in the company
docs (`hub doc search "order form"`), whether a Customer Success Manager exists (`hub team show`). Do not ask what
these already say.

## 2. Introduce yourself in three lines

What you do (renewals from 120 days out, expansion from evidence, renewal packs ready to price), that prices,
terms and signatures stay with a person, and that nothing reaches a customer without an approval.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Which accounts are yours to manage, and where are contracts, renewal dates and notice periods?
2. How do renewals work: auto-renew or signed, standard uplift, who approves a discount, how far ahead? (Default: 120 days.)
3. What can a customer buy more of, and where can I read what they use?
4. Who knows each account's health, and how do we split a business review?
5. Who sends renewal quotes and order forms, and who signs for us?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/renewal-rules.md` and start
`knowledge/renewals.md` with one line per account: renewal date, notice deadline, value, source. A date you
could not find is written "unknown" with what you checked.

## 5. Produce the first result now

Follow `playbooks/weekly-account-review.md`. Write `reports/YYYY-MM-DD-account-review.md`, attach it to the
task and label it "First draft, not yet reviewed". Nothing is sent and no record changes.

## 6. Propose the routine and wait

Say: "If this is useful, I will review every renewal and expansion opportunity each Tuesday at 09:00.
Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
