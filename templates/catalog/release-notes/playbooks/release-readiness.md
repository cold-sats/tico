# Release readiness

Triggered by a task naming a release ("is 2.15 ready for Thursday?") or the day before a scheduled release in
`knowledge/`. Budget 30 minutes. The outcome is one checklist with a go or no-go recommendation and its reason.
You tag, deploy and announce nothing.

---

## 1. Read the release

    hub task show <id>
    gh pr list -R <repo> --state merged --search "merged:>YYYY-MM-DD" --json number,title,labels
    gh run list -R <repo> --branch main --limit 10

The date of the last release is the start. List what is in it; mark anything labelled breaking, migration or
behind a feature flag.

## 2. Run the checklist

One line each, with its evidence and date:
- Main branch checks green on the release commit (`gh run list`).
- No open issue labelled blocker or for this milestone (`gh issue list -R <repo> --milestone <m>`).
- The QA Engineer's test plan for this release exists and its results are recorded (ask `issue-triage` if not).
- Database migrations listed, each with whether it can be reversed.
- Feature flags that change state with this release, and who turns each on.
- Rollback plan: the previous version and how it is restored, from `knowledge/`.
- Notes and changelog ready (`playbooks/weekly-release-notes.md`).
- Anyone who must know before release (support, sales) named, from `knowledge/`.

## 3. Recommend

Go when every line is green. No-go names the one to three items that block and who clears each. Unknown is
not green: a line you could not check says so. The decision is the release owner's.

## 4. Hand over

Write `reports/releases/<version>-readiness.md`, attach it, `hub file publish` it, commit, and
`hub task update <id> --status done --note` with the recommendation in the first line.
