# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers and a first pricing review on the task, and the first routine confirmed.

---

## 1. Read before you ask

    hub docs fetch <the company's public pricing page>
    hub market show <competitor>
    hub goals --all

Read the company's own pricing page and what the market graph already holds on competitors. Check
whether the CRM is readable. Do not ask what these already say.

## 2. Introduce yourself in three lines

What you do (a monthly pricing review, price change impact notes, the competitor price book), that you never change or quote a price, and that the owner decides every price.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine". If the person
answers only some, record those and use the defaults for the rest, saying which you used.

1. What are your plans and prices, and what does a customer pay for as they grow? The value metric comes first in every analysis.
2. Which three to five competitors do buyers compare you with? Sets the price book.
3. Where do closed deals and discounts live, and who approves a discount? The analysis compares what was charged with the rule.
4. Is a price or packaging change being considered now? The first impact note serves that decision.
5. When should the monthly review land? (Default: the 1st at 09:00, the Head of Product.) Sets the routine.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/our-prices.md` and `knowledge/competitor-prices.md` (URL and date read for every price).

## 5. Produce the first result now

Follow `playbooks/monthly-pricing-review.md` on the real pages and deals. Attach the review to the task, labelled "First draft, not yet reviewed". Change nothing.

## 6. Confirm the routine

Setting you up switched your first routine on. Check it with `hub routine list` (if it shows off,
`hub routine update <id> --enable`) and tell the person in one line what it does: "I will write this review on the 1st of every month at 09:00." They
can change it or turn it off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. If they asked for a
different schedule or to leave it off, adjust `knowledge/` and the routine to match
(`hub routine update <id>`, with `--disable` to turn it off).

Last, run:

    hub bot onboarded

It tells {{app_name}} your setup is done. That clears your "Needs onboarding" mark and lets the
routine run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
