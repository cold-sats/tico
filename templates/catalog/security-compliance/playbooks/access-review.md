# Access review

Triggered in the first month of each quarter by the monthly page, or by a task naming a tool. Budget
15 minutes per tool. The outcome is one review sheet per tool that its owner can decide in five
minutes, and afterwards the evidence that the review happened and its revocations were applied.

---

## 1. Get the list of who has access

An export of users and roles from the tool, provided by its admin or `it-support` (a task after
approval), or read directly where this bot has read access. Record the export's date: the review is of
that list.

## 2. Mark each line

Compare against `hub org` and last quarter's review. For each user: **left** (not on the roster),
**role changed** (their job no longer needs this role), **admin** (list every admin separately),
**dormant** (no login for 45 days, where the tool shows it), **shared or service account** (needs a
named owner), or **looks right**. Say why for every line not "looks right".

## 3. Put it to the owner

Write `knowledge/access-reviews/<quarter>.md` with one table per tool: user, role, mark, reason, and a
blank decision column (keep or revoke). Send it to the tool's owner as a task after approval. Admins
and anyone marked "left" are at the top.

## 4. Close it with evidence

When the owner decides, the revocations go to `it-support` or the tool's admin to apply. The review is
complete only when a fresh export shows them applied. File the owner's decision, the before and after
exports and the dates in the evidence folder, and log them in `knowledge/evidence-log.md`.
