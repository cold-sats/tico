# Weekly CI health report

Schedule: Tuesdays at 09:00 company time (routine `weekly-ci-health`), once a person has approved the first
report. Also run by hand. Budget 45 minutes. The outcome is one page: can people trust the merge check, what
got slower, and the three fixes worth an afternoon. Nothing on GitHub changes.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/thresholds.md`, `knowledge/pipeline.md`, `knowledge/flaky-tests.md` and last week's report. For
each fix planned last week, check whether it landed and whether the number moved.

## 2. Read the runs

For each workflow in `knowledge/pipeline.md`, the last 14 days: `gh run list ... --json ...`. Compute per
workflow: runs, failure rate, median and slowest duration, and compare the median with the previous 14 days.

## 3. Find the flaky tests

Commits with a failed run followed by a passed run and no new commit are flaky candidates. Read the failed
logs (`gh run view <id> --log-failed`) and name the failing test. A test past the threshold goes into the
register with its runs, a suspected cause and its owner. Existing entries: still flipping, fixed, or past
their deadline.

## 4. Find red-main streaks and deploys

Each stretch where the main branch's merge check stayed red: start (first failing run and commit), end,
length, and the cause if the log shows it. Count deploy runs and failed deploys from the deploy workflow.

## 5. Write three fix plans

Choose by time saved times people blocked: the slowest merge-gating job, the flakiest test, the most
common failure cause. For each: the file and job, the change, the expected effect, and how to verify.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-ci-health.md` in the shape of `knowledge/examples/ci-health.md`, `hub file
publish` it, commit, then `hub task update <id> --status done --note`: the headline and the path.
