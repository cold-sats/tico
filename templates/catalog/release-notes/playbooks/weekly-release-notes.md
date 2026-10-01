# Weekly release notes draft

Schedule: Fridays at 14:00 team time (routine `weekly-release-notes`), after setup. Also run by hand for a named release. Budget 40 minutes. The outcome is one draft: a suggested
version, a changelog entry and plain-language notes, plus the changes you could not classify. Nothing is
published and no tag is pushed.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/versioning.md`, `knowledge/voice.md` and `knowledge/labels.md`.

## 2. Find the range

    gh release list -R <repo> --limit 3
    gh pr list -R <repo> --state merged --search "merged:>YYYY-MM-DD" --json number,title,labels,mergedAt,body,url

The range is everything merged after the last release's date. If nothing has merged, say so on the task and
finish; do not invent a release.

## 3. Classify every change

Follow `playbooks/classify-a-change.md` for each. Sections, in this order: Added, Changed, Deprecated,
Removed, Fixed, Security. Breaking changes are marked at the top. Internal-only changes (refactors,
dependency bumps, tests) are counted and left out unless a user would notice.

## 4. Suggest the version

From the changes: any breaking change is a major bump, a new feature is a minor bump, only fixes is a patch
bump (semantic versioning). Write the suggestion and its reason in one line. If the repository does not use
semantic versioning, suggest a date-based name in its own style.

## 5. Write the draft

`reports/YYYY-MM-DD-release-notes.md` in the shape of `knowledge/examples/release-notes.md`:
1. **Suggested version and date range**, and the one change a user will notice most.
2. **Changelog entry**, in the repository's own CHANGELOG format, each line ending with its pull request link.
3. **Customer-facing notes**, plain language, in the voice in `knowledge/voice.md`, no internal names.
4. **Could not classify**: pull request, why, the question for a human.
5. **Left out**: counts by reason.
Then `hub file publish reports/YYYY-MM-DD-release-notes.md`.

## 6. Finish

Commit, then `hub task update <id> --status done --note`: the suggested version and why, changes included,
changes unclassified, and which repository you could not read. Publishing is a human's step.

## When a source fails

If a pull request body is empty or unreadable, put it in "Could not classify". If a repository cannot be
read, say the notes cover the others only.
