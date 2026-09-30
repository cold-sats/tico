# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a first brand book, a first audit
on a small sample, and the first routine confirmed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "brand"
    hub docs search "style guide"

Read any guide you find, and the company's home page. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (the brand book, reviews of copy and assets against it, a monthly audit of what went
public), that you never edit a live page or asset, and that a person approves every rule change.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Is there a brand guide, style guide or deck that shows how the company should sound and look?
2. Three words for how the company should sound, and one it should never sound like.
3. Which words do you always use for your product and customers, and which do you avoid?
4. Where does the company show up publicly?
5. Who approves a brand change, and who owns the logo and visual files?

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/brand.md` from the answers
and any guide found, marking each rule with its source ("from the 2025 deck", "said by Dana on this
task"). Mark what is still undecided under `## Open` rather than inventing it.

## 5. Produce the first result now

Follow `playbooks/monthly-brand-audit.md` on five public items (the home page, one email, two posts,
one listing). Write `reports/YYYY-MM-brand-audit.md`, attach it to the task and label it "First
draft, not yet reviewed".

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will audit what went public on the 1st of each month." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
