# Analyse a price change

Triggered by a task where a human is weighing a price or packaging change ("raise Pro by 15%", "move
SMS reminders to Pro"). Budget 60 minutes. The outcome is an impact note the owner can decide from.
Nothing is changed and no customer is told.

---

## 1. State the change exactly

    hub task show <id>

Write it as: which plans, which prices or limits, from when, for new customers only or everyone. If any
of these is open, lay out the variants side by side instead of guessing.

## 2. Find who it touches

From billing or CRM exports (read only): customers per plan and segment affected, their current and new
bill, and the ten accounts with the biggest increase. Count customers on annual terms whose renewal falls
in the next six months.

## 3. Estimate the effect

Revenue change per segment if nobody leaves, and the break-even churn: how many would have to leave for
the change to lose money. Say plainly that churn response is unknown unless a study measured it.

## 4. Lay out the options

Grandfathering (none, for a period, forever), notice periods, and exceptions (large accounts, non-profits),
each with its cost. Note contract terms that limit a change (ask the Contracts Manager to check wording;
you do not interpret contracts).

## 5. Write

`reports/YYYY-MM-DD-impact-<change>.md`: the recommendation-free summary line, the tables, the options,
the unknowns, and what would reduce them. `hub file publish`, commit, finish the task. The decision and
every customer message are the owner's.
