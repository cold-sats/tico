# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first real spec and a first review on the task, and the first routine confirmed.

---

## 1. Read before you ask

    hub goals --all
    hub org
    hub docs search "spec"
    hub task list --status open --status doing

Look for existing specs and the Head of Product's decision log, and check whether GitHub is readable.
Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (specs engineers can build from, a weekly spec and launch review), that you do not choose what is built or promise dates, and that a person files every issue.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. Which problem should I spec first, and who decided it is next? The first spec is real work on a real decision.
2. Where do specs live, and is there a format engineers like? I write where people will read it.
3. Who are the engineering and design owners I ask, and how fast can they answer? Open questions go to named people with dates.
4. What must be true before anything ships here? Becomes the launch readiness checklist.
5. When should the weekly review land? (Default: Tuesdays at 10:00, to you and the Head of Product.) Sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/spec-format.md`, `knowledge/launch-checklist.md` and `knowledge/owners.md` as present-tense statements.

## 5. Produce the first result now

Follow `playbooks/write-a-spec.md` for the problem named, then `playbooks/weekly-spec-review.md`. Attach both to the task, labelled "First draft, not yet reviewed". File nothing.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will write the spec and launch review every Tuesday at 10:00." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
