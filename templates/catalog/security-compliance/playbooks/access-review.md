# Access review

Triggered in the first month of each quarter by the monthly page, or by a task naming a tool. Budget
15 minutes per tool. The outcome is one review sheet per tool, requested access changes applied with Tools, and evidence of the result.

---

## 1. Get the list of who has access

An export of users and roles from the tool, provided by its admin or `it-support` (a task ), or read directly where this bot has read access. Record the export's date: the review is of
that list.

## 2. Mark each line

Compare against `hub team show` and last quarter's review. For each user: **left** (not on the roster),
**role changed** (their job no longer needs this role), **admin** (list every admin separately),
**dormant** (no login for 45 days, where the tool shows it), **shared or service account** (needs a
named owner), or **looks right**. Say why for every line not "looks right".

## 3. Record the findings

Write `knowledge/access-reviews/<quarter>.md` with one table per tool: user, role, mark, reason, and a
keep or revoke column based on the requested scope and access rules. Share it on the task. Ask the tool owner only about missing rules or an ambiguous account. Admins
and anyone marked "left" are at the top.

## 4. Close it with evidence

Apply requested changes with your granted admin Tools, or create a task for `it-support` naming the tool, account and rule. The review is complete only when a fresh export shows the changes applied. File the rules used, the before and after exports and the dates in the evidence folder, and log them in `knowledge/evidence-log.md`.
