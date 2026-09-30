# Weekly help article drafts

Schedule: Wednesdays at 10:00 company time (routine `weekly-article-drafts`), once a person has
approved the first drafts. Also run by hand on request. Budget 40 minutes. The outcome is one pack for
the reviewer: up to three drafts, the stale and duplicate list and the backlog. Nothing is published.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/style.md`, `knowledge/backlog.md` and `knowledge/health.md`.

## 2. Find what repeats

Read the last seven days of resolved work: Support Triage's tasks and reports, plus the mailbox if you
have it. A question is a repeat at three occurrences. Update the counts in `knowledge/backlog.md`. Skip
anything on the exclusion list and note it as skipped.

## 3. Choose at most three

1. Highest count with no article at all.
2. A question whose article exists but was contradicted by a newer answer.
3. Anything a reviewer asked for on a task.

A question that is really a defect is not an article: make one task for the fix owner and leave it out.

## 4. Draft

For each, follow `playbooks/write-an-article.md`. Save to `knowledge/drafts/<slug>.md`.

## 5. Check the help centre for health

Compare the drafts and the week's answers with the linked help centre. List stale articles (steps or
names that no longer match), duplicates and articles nobody could find. Each entry: title, what is wrong,
the evidence with a date, and the proposed action (update, merge, retire). Record them in
`knowledge/health.md`. You change nothing there.

## 6. Write the pack and hand it over

Write `reports/YYYY-MM-DD-article-drafts.md` in the shape of `knowledge/examples/article-draft.md`:
headline, drafts for review, stale and duplicate list, backlog top five, what you could not read. Then:

    hub files publish reports/YYYY-MM-DD-article-drafts.md

## 7. Finish

Commit, then `hub task update <id> --status done --note`: drafts written, flags raised, who reviews and
which sources you could not read. Always finish it: an open scheduled task absorbs the next.

## When a source fails

Name which source and what is therefore unknown, keep going with the rest, and say it in the pack. "No
repeats found" is never written for "could not read the tickets".
