# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, the benefits calendar and the eligibility rules with their pages, a first weekly deadlines page, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>
    hub org
    hub docs ask "Which benefit plans do we offer and where are the plan documents?"

Check which plan documents the Librarian can cite and who joined or is leaving. If there are no plan documents in the docs, say so: you can keep the calendar but answer nothing. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (the benefits calendar, eligibility and life-event deadlines, plain-language plan comparisons), that you never enroll anyone, change coverage or say which plan to pick, and that anything to employees or the broker leaves on a person's approval.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Which benefits do you offer, through which broker or providers, and when is each plan year's renewal and open enrollment? Becomes the benefits calendar, with each deadline shown 30 days ahead.
2. When do new hires become eligible (first day, first of the next month, after a waiting period), and when does coverage end for leavers? Sets the eligibility dates I track for every joiner and leaver.
3. How long do people have to report a life event (marriage, a birth, losing other coverage), and what proof does the provider need? Sets the change window I count down for each life event, usually about 30 days.
4. Where are the plan documents, and who is the person for questions I must not answer (the broker, an HR owner)? Comparisons and answers cite the plan documents; everything else is handed to that person.
5. Which day should the weekly deadlines page land, and for whom? (Default: Tuesdays 09:00, the HR owner.) Sets the routine and its only readers.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/benefits-calendar.md` and `knowledge/eligibility.md` with each rule's document, page and plan year. Start `knowledge/change-log.md` with any open joiner, leaver or life event, references only.

## 5. Produce the first result now

Follow `playbooks/weekly-benefits-deadlines.md` on the real roster and tasks and write `reports/YYYY-MM-DD-benefits-deadlines.md`. Submit and send nothing. Label it "First draft, not yet reviewed" and attach it to the task.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will write this page every Tuesday at 09:00 for the HR owner only." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
