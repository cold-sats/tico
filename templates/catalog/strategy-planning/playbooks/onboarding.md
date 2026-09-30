# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 15 minutes. The outcome is five recorded answers, a first draft on the task, built from the real goals, and the first routine confirmed.

---

## 1. Read before you ask

    hub goals --all
    hub org
    hub updates --kind weekly --limit 8
    hub meetings search --since <90 days ago>

Do not ask what these already say. If there are no goals at all, say so and draft from tasks and updates instead of asking the person to invent goals.

## 2. Introduce yourself in three lines

What you do (a quarterly plan and OKR draft, a grade of last quarter, a mid-quarter check-in), that you only read what is in {{app_name}}, and that you never create or change a goal.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. What is the company trying to achieve this year, in a sentence or two, and what is off the table? Becomes knowledge/strategy.md. Objectives are judged against it, so I stop proposing things you have already ruled out.
2. When does your quarter start and end, and who signs off the plan? (Default: calendar quarters, the owner signs off.) Sets the schedule of the drafts and who receives them. Nobody else sees a draft until you say so.
3. Do you already use OKRs or another goal format? If so, paste last quarter's. I match your format and grade last quarter's results before drafting the next.
4. How many objectives can the team really carry? (Default: three to five, about three key results each.) A plan longer than the team's capacity is a wish list. This sets the cap I hold the draft to.
5. Who owns each area (sales, product, support, operations), so a key result has a proposed owner to confirm? Every key result needs one named owner. I propose them; you confirm them.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/strategy.md` (aims and what is ruled out) and `knowledge/rhythm.md` (quarter dates, sign-off, cap, format) as present-tense statements.

## 5. Produce the first result now

Follow `playbooks/quarterly-plan.md` on the real record: the plan if the quarter is ending, otherwise a check-in. Write `reports/YYYY-MM-DD-quarterly-plan.md`, attach it to the task and label it "First draft, not yet reviewed". A first result the person can correct is the point of this session.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will draft this on the first of every month at 09:00, a full plan in the last month of a quarter." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
