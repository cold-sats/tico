# Weekly docs drift report

Schedule: Wednesdays at 10:00 team time (routine `weekly-docs-drift`), after setup. Also run by hand. Budget 45 minutes. The outcome is one report: merged changes that make a page wrong,
a draft fix for the top items, and pages you could not read. No docs are changed.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/docs-map.md`, `knowledge/style.md`, `knowledge/glossary.md` and last week's report.

## 2. List the changes users can see

    gh pr list -R <repo> --state merged --search "merged:>YYYY-MM-DD" --json number,title,body,files,url

Keep pull requests that change what a user sees or types: a renamed option, a new step, a removed feature, a
changed default, a new page or setting, a changed API field. Drop refactors and tests. Read the diff
(`gh pr diff <n> -R <repo>`) when the description is vague.

## 3. Find the pages each one affects

The docs in the repository if readable, and `knowledge/docs-map.md`. If an internal doc or the help centre is also wrong, that is a task to `librarian`, not a draft. For each affected
page decide: **wrong** (states something now false), **incomplete** (omits a new step or option), **missing**
(no page covers it), or **fine**. Quote the sentence that is wrong and the pull request that made it wrong.

## 4. Rank

1. Wrong, on a page many readers use (setup, sign in, billing, the API).
2. Missing pages for a feature already shipped.
3. Incomplete.
Draft fixes for the top three; list the rest in one line each.

## 5. Draft the fixes

Follow `playbooks/draft-a-doc-page.md`. Save each draft in `reports/drafts/YYYY-MM-DD-<page>.md` with the old
text, the new text and the pull request as the reason.

## 6. Write the report

`reports/YYYY-MM-DD-docs-drift.md` in the shape of `knowledge/examples/docs-drift-report.md`: headline,
top drifts with page, wrong text, cause and draft path, the rest, pages you could not read. Then
`hub file publish reports/YYYY-MM-DD-docs-drift.md`.

## 7. Finish

Commit, then `hub task update <id> --status done --note`: pages found, drafts made, unread sources. Always
finish it. Commit requested drafts with the repository Tools and run the required checks.

## When a source fails

If the docs site or repository cannot be read, say which pages were not compared. Never report "no drift" for a
page you could not open.
