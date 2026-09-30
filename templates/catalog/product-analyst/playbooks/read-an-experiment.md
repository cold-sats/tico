# Read an experiment

Triggered by a task asking whether an A/B test or a staged rollout worked. Budget 30 minutes. The outcome
is a readout that says what the evidence supports and whether it is safe to decide.

---

## 1. Find the plan

    hub task show <id>

Find the metric chosen before launch, the planned sample size or duration, and the variants. If there was
no plan, say so in line one: the readout is exploratory and cannot declare a winner.

## 2. Check it ran cleanly

Split close to what was intended (a large mismatch means assignment is broken); no change to the variant
mid-test; the planned sample or duration reached. If not reached, report the current numbers as
"not yet readable" and the date it will be.

## 3. Compute

For the planned metric: each variant's value, the difference, and its 95 percent interval. Guardrail
metrics (errors, cancellations, support tickets) beside it. Segment cuts only if planned; unplanned cuts
are labelled as leads to test, not results.

## 4. Write

`reports/YYYY-MM-DD-experiment-<name>.md`: the verdict in one line (better, worse, no detectable
difference, not yet readable), the numbers, the checks, and what a person would need to decide. Declaring
a winner is theirs. Publish, commit, finish the task.
