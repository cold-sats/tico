# Weekly issue digest

Schedule: Mondays at 09:00 team time (routine `weekly-issue-digest`), once a human has approved
the first digest. Also run by hand on request. Budget 30 minutes. The outcome is one report for the
recipient in `knowledge/areas.md`, and a batch of proposals waiting for a Confirm. Nothing on GitHub
changes.

---

## 1. Read what was decided last time

    hub task show <id>

Then `knowledge/themes.md` and the last digest in `reports/`. If this week's digest exists, update it.
The watermark is the newest issue number and `updatedAt` you recorded in `state.md`; read only what is
newer.

## 2. Pull the issues

    gh issue list -R <repo> --state open --json number,title,labels,createdAt,updatedAt,author --limit 200
    gh issue list -R <repo> --state closed --search "closed:>=<last Monday>" --json number,title

For each repository in `state.md`. Note any repository you could not read.

## 3. Triage each new or updated issue

Follow `playbooks/triage-an-issue.md` for every issue created or updated since the watermark. Unlabelled
issues older than a day are listed first. For an issue already waiting on a reporter, note how many
days it has waited. Suggest the maintainer close it only when it has waited longer than the repository's
own stale rule, and say that a human must do it.

## 4. Find the themes

Compare the week's issues against `knowledge/themes.md`. Three or more issues about the same thing
is a theme: add it with the issue numbers and dates, and put it in the digest. A theme with a rising
count is the one thing to lead with.

## 5. Write and publish

Write `reports/YYYY-MM-DD-issue-digest.md` in the shape of `knowledge/examples/issue-digest.md`:
headline, needs a human today, proposed labels and duplicates by area, waiting on a reporter with the
drafted question, themes, and what you could not read. Then:

    hub file publish reports/YYYY-MM-DD-issue-digest.md

Request the label approval described in `playbooks/triage-an-issue.md` step 6. Once the routine is
armed, tell the recipient with `hub message send --fyi <person> "<one line and the link>"`.

## 6. Finish

Update the watermark in `state.md`, commit, then `hub task update <id> --status done --note` with the
headline, counts, and the report path. Always finish it: an open routine task absorbs next Monday's.
