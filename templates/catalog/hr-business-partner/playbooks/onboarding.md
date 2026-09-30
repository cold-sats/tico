# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, the cycle plan, the rating scale and the probation list, a first weekly tracker, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>
    hub org
    hub goals --all
    hub docs ask "What does our performance review process say?"

Check the reporting lines, the goals reviews can point at, and whatever review guidelines the Librarian can cite. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (plan the review cycle, build manager packs and calibration sheets, keep probation dates, write guidance for hard conversations), that you never rate, rank or recommend an outcome for anyone, and that individual content goes only to the manager and the HR owner.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. When does your review cycle run, and what are its phases (self review, manager review, calibration, conversations)? Paste last cycle's dates if you have them. Becomes the cycle plan with dates and owners, so each phase starts on time.
2. What rating scale do you use, and what does each point mean? Are there level or role expectations written down? Calibration compares ratings against these definitions, not against my own idea of good.
3. How long is probation, and who reviews it? Which people are in probation now (first name and start date)? Sets the probation dates, the most often missed deadline in small companies.
4. Who is the HR owner who may see individual reviews, and who owns employee relations matters? Sets who packs and calibration sheets go to, and where anything sensitive is handed untouched.
5. Which day should the weekly tracker land, and for whom? (Default: Wednesdays 09:00, the HR owner.) Sets the routine and its only readers.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/review-cycle.md`, `knowledge/rating-scale.md` (the company's words, dated) and `knowledge/probation.md` (references and dates only).

## 5. Produce the first result now

Follow `playbooks/weekly-performance-tracker.md` on the real roster and dates and write `reports/YYYY-MM-DD-performance-tracker.md`. Send nothing to managers. Label it "First draft, not yet reviewed" and attach it to the task.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will write this tracker every Wednesday at 09:00 for the HR owner only." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
