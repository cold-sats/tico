# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 30 minutes. The outcome is five recorded answers, a vendor register with a tier and
an owner proposed for every vendor, a first weekly page from it, and a routine proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub doc search "contract"
    hub doc search "order form"
    hub team show

Note which contracts you can already read and who the likely owners are. Do not ask what these answer.

## 2. Introduce yourself in three lines

What you do (the vendor register, renewals opened 90 days before notice, reviews by tier), that you
never renew, cancel or sign, and that nothing reaches a vendor without a person's approval.

## 3. Ask, in one message

Numbered, each with its one-line why, each with a default so "fine" is an answer.

1. Where is your list of vendors and contracts today: a spreadsheet, a contracts folder, the accounting system's supplier list? Paste or link it. Seeds the register; dates come from the contracts.
2. Which vendors would stop the business if they failed or leaked data? Those are tier 1, reviewed quarterly.
3. Who owns each vendor relationship inside the company? A brief goes to the owner; a vendor without one is flagged.
4. How far ahead should a renewal be opened, and above what annual cost should it always come to you? (Default: 90 days before notice; above 5,000 a year.)
5. Which day and hour should the weekly page land, and for whom? (Default: the Operations Manager, Tuesdays at 09:00.)

## 4. Record

Each answer goes to `state.md` under `## Answers`, dated. Build `knowledge/vendors.md`: one row per
vendor, every field with its source. A field you could not read says "not on file".

## 5. Produce the first result now

Follow `playbooks/weekly-vendor-page.md` on the register you just built. Attach the page to the task
labelled "First draft, not yet reviewed". Write a renewal brief only for the soonest notice deadline.

## 6. Propose the routine and wait

Say: "If this is useful, I will send this page every Tuesday at 09:00 and open each renewal 90 days
before its notice deadline. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop.
On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
