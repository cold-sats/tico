# Weekly dependency and advisory report

Schedule: Mondays at 08:00 team time (routine `weekly-security-report`), once a human has approved the
first report. Also run by hand. Budget 45 minutes. The outcome is one page: what to patch first and why, in
the order to merge it. Nothing is dismissed, merged or changed.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/patch-policy.md`, `knowledge/exposure.md`, `knowledge/ledger.md` and last week's report. Check
whether last week's plan was merged (`gh pr list -R <repo> --state merged --search "merged:>YYYY-MM-DD"`).

## 2. Collect the alerts

For each repository in scope: open Dependabot pull requests and the advisories they name, plus any
advisory a human handed you on a task. For each: package, installed and fixed versions, GHSA or CVE, the
advisory's severity.

## 3. Rank each one

Follow `playbooks/assess-an-advisory.md`. Tier 1: on CISA's Known Exploited Vulnerabilities list, or a
high EPSS probability (0.1 or more) and reachable on an internet-facing service. Tier 2: reachable, or
critical and reach unknown. Tier 3: everything else, including dev-only and test-only packages. Each line
carries its reason.

## 4. Check for committed credentials

Search open pull requests' diffs and the default branch for credential patterns (private keys, cloud and
API tokens, `.env` files) in a read-only clone. Report each by file, commit and credential kind only, and
the rotation step. Never the value.

## 5. Write the patch plan

Group upgrades that land together (one lockfile change fixing three alerts), order by tier then by effort,
and flag major-version bumps that need a code change. Name the owner from `knowledge/exposure.md` and the
deadline from the policy.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-security-report.md` in the shape of `knowledge/examples/security-report.md`,
`hub files publish` it with `--scope task`, and create a task for the owner of each tier 1 item after the
requester's yes. Update `knowledge/ledger.md`, commit, then `hub task update <id> --status done --note`.
