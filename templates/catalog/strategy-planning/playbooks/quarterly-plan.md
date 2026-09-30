# Quarterly plan and OKR draft

Schedule: the first of each month at 09:00 team time (routine `quarterly-plan`), once a human
has approved the first draft. Also run by hand. Budget 45 minutes. The outcome is one report for the
owner: in the last month of a quarter, last quarter graded and next quarter drafted; in the other
months, a mid-quarter check-in. Nothing in Tico changes.

---

## 1. Decide which report this is

Read `knowledge/rhythm.md` for the quarter dates. In the last month of a quarter, write the plan.
Otherwise write the check-in (step 6). If the task names one, do that.

## 2. Read the record

    hub goals --all
    hub goal show <id>
    hub kpi readings <kpi id>
    hub updates --kind weekly --limit 12
    hub meetings search --since <quarter start>

Then `knowledge/strategy.md`, `knowledge/scorecard.md` and last quarter's report. A source you cannot
read is named in the closing line.

## 3. Grade last quarter

Follow `playbooks/grade-a-quarter.md`. Write the result into the report and `knowledge/scorecard.md`.

## 4. Draft next quarter

1. Pick the one bet: the single outcome that would make the quarter a success, from
   `knowledge/strategy.md` and the goals still live.
2. Draft three to five objectives, each an outcome in plain words with about three key results.
3. Each key result: a metric, its baseline (with source and date), a target, a date, a proposed owner
   marked "to confirm", and committed or aspirational.
4. Carry over what did not finish only if it still serves the bet; say why.
5. List what you left out and why. A short list of what is ruled out is part of the plan.

## 5. Check it against the cap

More than the cap in `knowledge/rhythm.md`: cut to the cap and list the rest under "Not this quarter".
Any key result phrased as an activity is rewritten or moved to "How we might get there".

## 6. The mid-quarter check-in

One line per key result: reading, target, confidence from 0 to 1 that it lands, and the one fact
behind the confidence. Then three lines: what is off track, what needs a decision, what to drop.

## 7. Write and hand over

Write `reports/YYYY-MM-DD-quarterly-plan.md` in the shape of `knowledge/examples/quarterly-plan.md`,
then `hub files publish reports/YYYY-MM-DD-quarterly-plan.md`. Commit, then `hub task update <id>
--status done --note`: the headline, the path, what you could not read. Always finish the task.
