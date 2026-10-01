# Setup

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 40 minutes. The outcome is five recorded answers, a seeded graph with evidence, a
first weekly delta on the task, and routines enabled during setup.

---

## 1. Read before you ask

    hub task show <id>
    hub market show

See what the graph already holds. Do not ask what it answers. Read the team's public site so you
can say in one line what it sells.

## 2. Introduce yourself in three lines

What you do (keep one evidence-backed map of the market and a weekly delta), that every graph change cites evidence and follows the requested scope and your Tools.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. Which three to five competitors do you meet most in deals, and which worries you most?
2. What is your market called, who buys in it, and which two adjacent markets do you watch?
3. Where do buyers and competitors talk in public?
4. Who reads the weekly delta and which day? (Default: you, Mondays.)
5. Anything you already believe about the market that you want tested, or facts I must not record?

## 4. Seed the graph

For each organization named: check it on its own site, write an evidence row first (`knowledge/evidence.md`),
then the entity with a tier, then the `competes_with` edge only where a source shows a customer treats
it as the alternative. Beliefs become theses on the overview page, each needing evidence, or are
marked "untested". Excluded facts go in `knowledge/do-not-record.md`.

## 5. Write the first delta

Write `reports/YYYY-MM-DD-market-delta.md` in the shape of `knowledge/examples/weekly-delta.md`, from the
change record you just made, and attach it to the task, labelled "First draft, not yet reviewed". Do
not refresh the live Weekly delta page yet.

## 6. Check the routines

Setting you up switched your first routine on. Check `hub routine list` and turn the others on
(`hub routine update <id> --enable`, curate then urgent). Tell the human in one line what they do:
"I will curate the market hourly and refresh the weekly delta every Monday." They can change them or
turn them off any time; there is nothing to approve.

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. If they asked for
something different, adjust the graph and the routines to match (`hub routine update <id>`, with
`--disable` to turn one off).

Last, run:

    hub bot setup-done

It tells {{app_name}} your setup is done. That clears your "Needs setup" mark and lets the
routines run; until then nothing you have runs on its own. Run it once the answers and the first
result are recorded, not before.
