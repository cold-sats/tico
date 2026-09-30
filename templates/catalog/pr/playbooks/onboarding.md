# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first PR review on the task from
real coverage, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>
    hub calendar upcoming
    hub updates --bot product-marketing

Search the public web for the company's name and products in the last 90 days. Note launches already
planned. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (the media list, the coverage log, releases and pitches prepared), that you never contact
a journalist or promise anything, and that a person sends or approves every pitch.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What news is coming in the next three months that might interest press?
2. Which outlets and reporters matter most to your buyers, and who has covered you before?
3. Who may speak to press, and who approves a release or pitch?
4. What must never be said publicly yet?
5. What could turn into bad press, and what would you want ready?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/stories.md`,
`knowledge/media-list.md` (only reporters whose recent articles you have read) and
`knowledge/rules.md` (spokesperson, approver, not-yet-public list, risks).

## 5. Produce the first result now

Follow `playbooks/weekly-pr-review.md`. Write `reports/YYYY-MM-DD-pr.md`, attach it to the task and
label it "First draft, not yet reviewed".

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will write this review every Tuesday at 09:00." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
