# Investigate a red build

Triggered by a task or message about a failing run ("main is red", "why does deploy keep failing?").
Budget 20 minutes. The outcome is the cause, the first bad commit, and the fix or the owner. You rerun and
revert nothing.

---

## 1. Find the first failure

    hub task show <id>
    gh run list -R <repo> --branch main --workflow <name> --limit 30

Walk back to the last green run. The first red run after it names the commit range to look at.

## 2. Read the log

`gh run view <id> -R <repo> --log-failed`. Classify: a test assertion (product bug or broken test), a
flaky signature (timeout, port in use, order-dependent state), infrastructure (runner, network, rate
limit, expired credential), or a dependency (a new release upstream, a yanked version). Quote the three
lines that show it; redact anything credential.

## 3. Check flakiness before blaming a commit

Has this test flipped before (`knowledge/flaky-tests.md`)? Did the same commit pass on another run? If
so, it is flaky, not broken: say so, and propose the register entry.

## 4. Answer

On the task, in four lines: **Cause** with the quoted evidence; **First bad run and commit** (link);
**Fix** (the change or the revert a human should consider) or **Owner** from `knowledge/pipeline.md`;
**Confidence** and what would confirm it. `hub task update <id> --status done --note`. A product bug also
becomes a note for the QA Engineer to triage, after the requester's yes.
